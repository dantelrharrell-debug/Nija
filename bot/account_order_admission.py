"""Transactional entry admission boundary; not installed in the live runtime.

An audited collector must read authenticated account state and reconcile it with
this transaction's ledger snapshot. No request-supplied evidence is accepted.
The store does not replace distributed writer fencing or protective exit routes.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Callable, Iterator, Mapping

from .order_admission_policy import Candidate, CurrentFact, OrderOutcome, evaluate_candidate


class AdmissionDenied(RuntimeError):
    """Local authorization denial, never an exchange rejection."""


@dataclass(frozen=True)
class Reservation:
    """One durable, single-use entry authorization bound to an exact intent."""

    token: str
    candidate: Candidate


# Installed collectors are dependencies, not facts supplied by an order caller.
Collector = Callable[[Candidate, sqlite3.Connection], tuple[Mapping[str, CurrentFact], OrderOutcome]]
Fence = Callable[[Candidate], None]


class AccountOrderAdmission:
    """Serialize entries across processes using the canonical persistent ledger.

    Account names must identify the broker account independently of API-key
    rotation, symbol and process. All entry producers must share this database.
    A missing database/schema is an error, never evidence of an empty history.
    No lease timeout, ACK or exception releases a reservation. Deliberately no
    general delete/release API: terminal release requires a separately audited
    broker-fill/ledger reconciliation integration.
    """

    def __init__(self, ledger: Path, collector: Collector, fence: Fence):
        self.ledger = Path(ledger)
        if not callable(collector) or not callable(fence):
            raise TypeError("verified_collector_and_writer_fence_required")
        self.collector = collector
        self.fence = fence

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        if self.ledger.is_symlink() or not self.ledger.is_file():
            raise AdmissionDenied("canonical_ledger_missing_or_symlink")
        conn = sqlite3.connect(self.ledger.resolve().as_uri() + "?mode=rw", uri=True, timeout=5)
        try:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def install_schema(self) -> None:
        """Explicit migration on an existing ledger; grants no authorization."""
        with self._transaction() as conn:
            for table in ("trade_ledger", "open_positions", "completed_trades", "strategy_order_intents"):
                if not conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone():
                    raise AdmissionDenied("canonical_ledger_schema_missing:" + table)
            conn.execute("""CREATE TABLE IF NOT EXISTS account_entry_reservations (
                token TEXT PRIMARY KEY,
                account TEXT NOT NULL,
                credential_fingerprint TEXT NOT NULL,
                writer_generation INTEGER NOT NULL,
                intent_digest TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('reserved','submitting','reconciled')),
                created_at REAL NOT NULL,
                UNIQUE(account, intent_digest)
            )""")
            conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS account_entry_single_unresolved
                ON account_entry_reservations(account) WHERE state != 'reconciled'""")

    def _check(self, candidate: Candidate, conn: sqlite3.Connection) -> None:
        # Collector receives a read-only view of the locked ledger transaction.
        # It must fail if authenticated scope, pagination, coverage or matching
        # historical fills are incomplete; zero rows alone is not certification.
        conn.execute("PRAGMA query_only=ON")
        try:
            facts, outcome = self.collector(candidate, conn)
        finally:
            conn.execute("PRAGMA query_only=OFF")
        decision = evaluate_candidate(candidate, facts, outcome, now=time.time())
        if not decision.eligible_for_canonical_dispatch:
            raise AdmissionDenied(";".join(decision.reasons))
        # A collector label is not authentication. The reviewed runtime adapter
        # is responsible for producing these two mandatory independent facts.
        self.fence(candidate)

    def reserve(self, candidate: Candidate) -> Reservation:
        """Check account/ledger evidence and atomically reserve this account."""
        with self._transaction() as conn:
            self._check(candidate, conn)
            token = secrets.token_hex(32)
            try:
                conn.execute("""INSERT INTO account_entry_reservations
                    (token,account,credential_fingerprint,writer_generation,intent_digest,state,created_at)
                    VALUES (?,?,?,?,?,'reserved',?)""", (
                        token, candidate.account, candidate.credential_fingerprint,
                        candidate.writer_generation, candidate.intent_digest, time.time(),
                    ))
            except sqlite3.IntegrityError as exc:
                raise AdmissionDenied("account_unresolved_or_intent_replay") from exc
        return Reservation(token, candidate)

    def consume(self, reservation: Reservation) -> None:
        """Recheck all evidence and fencing before committing the send boundary.

        This is single use. Commit must succeed before dispatch. If the process
        dies after commit or a broker result is uncertain, the account stays
        blocked. Never call a broker inside this transaction or retry consume.
        The terminal broker transport must still recheck its writer/nonce fence.
        """
        if type(reservation) is not Reservation:
            raise AdmissionDenied("reservation_invalid")
        candidate = reservation.candidate
        with self._transaction() as conn:
            row = conn.execute("""SELECT account,credential_fingerprint,writer_generation,intent_digest,state
                FROM account_entry_reservations WHERE token=?""", (reservation.token,)).fetchone()
            expected = (candidate.account, candidate.credential_fingerprint,
                        candidate.writer_generation, candidate.intent_digest, "reserved")
            if row != expected:
                raise AdmissionDenied("reservation_consumed_or_identity_mismatch")
            self._check(candidate, conn)
            conn.execute("UPDATE account_entry_reservations SET state='submitting' WHERE token=?",
                         (reservation.token,))
