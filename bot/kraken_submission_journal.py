"""SQLite write-ahead reservations for a single Kraken account.

This module owns no broker or nonce. The writer must commit a reservation before
calling the transport. An acknowledgment records an exchange order ID without
clearing the reservation. An independently reviewed reconciliation source
must verify the terminal exchange order and local ledger before settlement.
"""

from collections.abc import Callable, Mapping
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import re
import sqlite3
import time
import uuid


class SubmissionDenied(RuntimeError):
    """The caller must skip dispatch when it cannot claim a durable reservation."""


def initialize_journal(path: Path, account_scope: str) -> None:
    """Provision an empty journal explicitly in an existing private directory."""
    if not account_scope:
        raise ValueError("account scope required")
    # The canonical name becomes visible only after the schema transaction
    # commits. A hard link on the same filesystem never replaces an old journal.
    with TemporaryDirectory(prefix=".kraken-journal-", dir=path.parent) as staging:
        staged = Path(staging) / "journal.db"
        staged.touch(mode=0o600, exist_ok=False)
        with closing(sqlite3.connect(staged)) as db, db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE account (scope TEXT PRIMARY KEY NOT NULL)")
            db.execute("INSERT INTO account VALUES (?)", (account_scope,))
            db.execute("""
                CREATE TABLE submission (
                    intent_id TEXT PRIMARY KEY NOT NULL,
                    reserved_at REAL NOT NULL,
                    broker_order_id TEXT UNIQUE
                )
            """)
            db.execute("""
                CREATE TABLE submission_resolution (
                    intent_id TEXT PRIMARY KEY NOT NULL REFERENCES submission(intent_id),
                    observed_at REAL NOT NULL,
                    terminal_status TEXT NOT NULL,
                    broker_evidence_sha256 TEXT NOT NULL,
                    ledger_evidence_sha256 TEXT NOT NULL
                )
            """)
        os.link(staged, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


class KrakenSubmissionJournal:
    """Atomically reserve an intent and retain unresolved attempts across restarts."""

    def __init__(self, path: Path, account_scope: str):
        self.path = path
        self.account_scope = account_scope

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if self.path.is_symlink() or not self.path.is_file():
            raise SubmissionDenied("durable submission journal missing")
        mode = "ro" if readonly else "rw"
        return sqlite3.connect(f"{self.path.resolve().as_uri()}?mode={mode}", uri=True)

    def _check_scope(self, db: sqlite3.Connection) -> None:
        if db.execute("SELECT scope FROM account").fetchall() != [(self.account_scope,)]:
            raise SubmissionDenied("submission journal account scope mismatch")

    def _check_resolution_links(self, db: sqlite3.Connection) -> None:
        if db.execute(
            """SELECT 1 FROM submission_resolution AS r WHERE NOT EXISTS
               (SELECT 1 FROM submission AS s WHERE s.intent_id=r.intent_id) LIMIT 1"""
        ).fetchone():
            raise SubmissionDenied("submission journal contains terminal evidence without a reservation")

    def _client_order_id(self, intent_id: str) -> str:
        namespace = uuid.uuid5(uuid.NAMESPACE_URL, f"nija:kraken:{self.account_scope}")
        return uuid.uuid5(namespace, intent_id).hex

    def reserve(self, intent_id: str) -> str:
        """Commit an exclusive reservation before dispatching to Kraken."""
        if not isinstance(intent_id, str) or not intent_id or intent_id != intent_id.strip():
            raise SubmissionDenied("stable intent ID required")
        try:
            with closing(self._connect()) as db, db:
                db.execute("PRAGMA synchronous=FULL")
                db.execute("BEGIN IMMEDIATE")
                self._check_scope(db)
                self._check_resolution_links(db)
                if db.execute("SELECT 1 FROM submission WHERE intent_id=?", (intent_id,)).fetchone():
                    raise SubmissionDenied("intent already reserved")
                if db.execute(
                    """SELECT 1 FROM submission AS s WHERE NOT EXISTS
                       (SELECT 1 FROM submission_resolution WHERE intent_id=s.intent_id) LIMIT 1"""
                ).fetchone():
                    raise SubmissionDenied("unresolved Kraken submission")
                db.execute("INSERT INTO submission VALUES (?, ?, NULL)", (intent_id, time.time()))
        except sqlite3.Error as exc:
            raise SubmissionDenied("could not commit durable submission reservation") from exc
        return self._client_order_id(intent_id)

    def record_ack(self, intent_id: str, broker_order_id: str) -> None:
        """Record the transport's order ID without granting permission to retry."""
        if not isinstance(broker_order_id, str) or not broker_order_id.strip():
            raise SubmissionDenied("broker order ID required")
        try:
            with closing(self._connect()) as db, db:
                db.execute("PRAGMA synchronous=FULL")
                db.execute("BEGIN IMMEDIATE")
                self._check_scope(db)
                updated = db.execute(
                    """UPDATE submission SET broker_order_id=?
                       WHERE intent_id=? AND (broker_order_id IS NULL OR broker_order_id=?)""",
                    (broker_order_id, intent_id, broker_order_id),
                )
                if updated.rowcount != 1:
                    raise SubmissionDenied("missing reservation or conflicting acknowledgment")
        except sqlite3.Error as exc:
            raise SubmissionDenied("could not commit broker acknowledgment") from exc

    def reconcile_submission(
        self,
        intent_id: str,
        *,
        verify_terminal_order: Callable[..., Mapping],
    ) -> None:
        """Persist terminal proof from the independently reviewed reconciliation source.

        The callback must authenticate the pinned Kraken account and verify the
        order's terminal state against the independently persisted local ledger.
        Routing metadata, an ACK, and broker-only fill proof are insufficient.
        """
        try:
            with closing(self._connect(readonly=True)) as db, db:
                db.execute("BEGIN")
                self._check_scope(db)
                row = db.execute(
                    "SELECT reserved_at, broker_order_id FROM submission WHERE intent_id=?",
                    (intent_id,),
                ).fetchone()
            if row is None:
                raise SubmissionDenied("submission reservation missing")
            reserved_at, broker_order_id = row
            if broker_order_id:
                proof = verify_terminal_order(self.account_scope, intent_id, broker_order_id, reserved_at)
            else:
                proof = verify_terminal_order(
                    self.account_scope, intent_id, None, reserved_at,
                    client_order_id=self._client_order_id(intent_id),
                )
            if not isinstance(proof, Mapping):
                raise SubmissionDenied("terminal reconciliation unavailable")
            observed_at = proof.get("observed_at")
            status = proof.get("terminal_status")
            broker_hash = proof.get("broker_evidence_sha256")
            ledger_hash = proof.get("ledger_evidence_sha256")
            proven_order_id = proof.get("broker_order_id")
            exact_match = (proven_order_id == broker_order_id if broker_order_id else
                           proof.get("client_order_id") == self._client_order_id(intent_id))
            if (proof.get("account_scope") != self.account_scope or proof.get("intent_id") != intent_id
                    or not exact_match or not isinstance(proven_order_id, str) or not proven_order_id.strip()
                    or status not in ("closed", "canceled", "expired")
                    or type(observed_at) not in (int, float) or not reserved_at <= observed_at <= time.time()
                    or not all(isinstance(pin, str) and re.fullmatch(r"[0-9a-f]{64}", pin)
                               for pin in (broker_hash, ledger_hash))):
                raise SubmissionDenied("terminal reconciliation identity or evidence invalid")

            with closing(self._connect()) as db, db:
                db.execute("PRAGMA synchronous=FULL")
                db.execute("PRAGMA foreign_keys=ON")
                db.execute("BEGIN IMMEDIATE")
                self._check_scope(db)
                current = db.execute(
                    "SELECT reserved_at, broker_order_id FROM submission WHERE intent_id=?",
                    (intent_id,),
                ).fetchone()
                if current != row:
                    raise SubmissionDenied("submission changed during reconciliation")
                resolution = (observed_at, status, broker_hash, ledger_hash)
                saved = db.execute(
                    """SELECT observed_at, terminal_status, broker_evidence_sha256, ledger_evidence_sha256
                       FROM submission_resolution WHERE intent_id=?""",
                    (intent_id,),
                ).fetchone()
                if saved is None:
                    if broker_order_id is None:
                        db.execute("UPDATE submission SET broker_order_id=? WHERE intent_id=?",
                                   (proven_order_id, intent_id))
                    db.execute("INSERT INTO submission_resolution VALUES (?, ?, ?, ?, ?)", (intent_id, *resolution))
                elif saved != resolution:
                    raise SubmissionDenied("conflicting terminal reconciliation")
        except sqlite3.Error as exc:
            raise SubmissionDenied("could not commit terminal reconciliation") from exc

    def unresolved_count(self) -> int:
        """Return the locally recorded count without claiming interval coverage."""
        with closing(self._connect(readonly=True)) as db, db:
            db.execute("BEGIN")
            self._check_scope(db)
            self._check_resolution_links(db)
            return db.execute(
                """SELECT COUNT(*) FROM submission AS s WHERE NOT EXISTS
                   (SELECT 1 FROM submission_resolution WHERE intent_id=s.intent_id)"""
            ).fetchone()[0]


def configured_journal_path() -> str:
    """Return the configured direct-order journal path, if opted in."""
    return os.environ.get("NIJA_KRAKEN_SUBMISSION_JOURNAL_PATH", "").strip()


def query_direct_order(broker, method, params, *, assert_deadline):
    """Route an opted-in direct order through a durable reservation.

    Transport failures and replies without a unique acknowledgment leave
    the reservation unresolved. The verified recovery path must resolve it.
    """
    # Batch submission has no durable per-order reservation/ACK mapping.
    # Reject before any transport call, even when a journal path is configured.
    if method == "AddOrderBatch":
        raise SubmissionDenied("batch Kraken order submission lacks journal support")
    path = configured_journal_path()
    if method == "AddOrder" and params.get("validate") is True:
        return broker.api.query_private(method, params)
    if method == "AddOrder" and not path:
        raise SubmissionDenied("durable Kraken submission journal not configured")
    if not path:
        return broker.api.query_private(method, params)
    if method != "AddOrder":
        raise SubmissionDenied("order method lacks journal support")

    from bot.runtime_correlation import get_runtime_correlation
    from scripts.nija_kraken_readonly_history_collector_v441 import _broker_account_scope

    scope = _broker_account_scope(broker)
    journal = KrakenSubmissionJournal(Path(path), scope)
    intent_id = get_runtime_correlation().get("intent_id")
    if "userref" in params or "cl_ord_id" in params:
        raise SubmissionDenied("order already contains a client reference")
    client_order_id = journal.reserve(intent_id)
    assert_deadline(method)
    result = broker.api.query_private(method, {**params, "cl_ord_id": client_order_id})
    if isinstance(result, dict) and result.get("error") == []:
        payload = result.get("result")
        txids = payload.get("txid") if isinstance(payload, dict) else None
        if isinstance(txids, list) and len(txids) == 1:
            journal.record_ack(intent_id, txids[0])
    return result
