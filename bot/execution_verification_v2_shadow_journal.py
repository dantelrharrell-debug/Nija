"""Durable v2 order-evidence SHADOW journal, never a trading authority.

There are no imports from dispatch, risk, readiness, broker, or ledger modules.
No code runs at import time. Database creation and every write are explicit.
Stored events are untrusted shadow CANDIDATES until independent authenticated
adapter verification and broker/ledger reconciliation have been implemented.
Neither a journal row nor a client/venue-provided digest grants live authority.
"""
from __future__ import annotations

from contextlib import contextmanager, closing
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3
from typing import Any, Iterator


_SHADOW_APPLICATION_ID = 0x4E4A5332  # NJS2: only this SQLite application is eligible.


class ShadowEvidenceError(ValueError):
    """Input mismatch or durable evidence invariant failed; keep fail-closed."""


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ShadowEvidenceError("invalid_" + field)
    result = value.strip()
    if not result or len(result) > 160 or any(c.isspace() for c in result):
        raise ShadowEvidenceError("invalid_" + field)
    return result


def _digest(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        c not in "0123456789abcdef" for c in value
    ):
        raise ShadowEvidenceError("invalid_evidence_digest")
    return value


def _positive(value: Any) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ShadowEvidenceError("invalid_positive_quantity")
    try:
        v = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ShadowEvidenceError("invalid_positive_quantity") from None
    if not v.is_finite() or v <= 0:
        raise ShadowEvidenceError("invalid_positive_quantity")
    return v


@contextmanager
def _transaction(path: str | Path, *, create: bool = False) -> Iterator[sqlite3.Connection]:
    target = Path(path)
    if (not target.is_absolute() or target.is_symlink() or not target.parent.is_dir()\n            or "shadow" not in target.stem.lower()):
        raise ShadowEvidenceError("shadow_database_path_invalid")
    existed = target.exists()
    if not create and not target.is_file():
        raise ShadowEvidenceError("shadow_database_uninitialized")
    prior_size = target.stat().st_size if existed and target.is_file() else 0
    try:
        with closing(sqlite3.connect(str(target), timeout=5.0)) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=FULL")
            app_id = conn.execute("PRAGMA application_id").fetchone()[0]
            if create:
                if existed and prior_size > 0 and app_id != _SHADOW_APPLICATION_ID:
                    raise ShadowEvidenceError("shadow_database_identity_mismatch")
            elif app_id != _SHADOW_APPLICATION_ID:
                raise ShadowEvidenceError("shadow_database_identity_mismatch")
            conn.execute("BEGIN IMMEDIATE")
            try:
                if create:
                    conn.execute("PRAGMA application_id = " + str(_SHADOW_APPLICATION_ID))
                    conn.execute("PRAGMA user_version = 1")
                yield conn
            except BaseException:
                conn.rollback()
                raise
            else:
                conn.commit()
    except sqlite3.Error:
        raise ShadowEvidenceError("shadow_database_unavailable") from None


def initialize_shadow_journal(path: str | Path) -> None:
    """Explicit opt-in schema creation, never invoked by import/startup."""
    with _transaction(path, create=True) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS shadow_order_intents (
                venue TEXT NOT NULL,
                account_fingerprint TEXT NOT NULL,
                tenant_fingerprint TEXT NOT NULL,
                client_order_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
                request_qty TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                writer_generation INTEGER NOT NULL CHECK (writer_generation > 0),
                broker_order_id TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (venue, account_fingerprint, client_order_id)
            )"""
        )
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS unique_shadow_broker_order
               ON shadow_order_intents(venue, account_fingerprint, broker_order_id)
               WHERE broker_order_id != ''"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS shadow_fill_candidates (
                venue TEXT NOT NULL,
                account_fingerprint TEXT NOT NULL,
                client_order_id TEXT NOT NULL,
                execution_id TEXT NOT NULL,
                event_digest TEXT NOT NULL,
                fill_qty TEXT NOT NULL,
                fill_price TEXT NOT NULL,
                cumulative_qty TEXT NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY (venue, account_fingerprint, execution_id),
                FOREIGN KEY (venue, account_fingerprint, client_order_id)
                REFERENCES shadow_order_intents(venue, account_fingerprint, client_order_id)
            )"""
        )


def persist_shadow_intent(
    path: str | Path, *, venue: str, account_fingerprint: str,
    tenant_fingerprint: str, client_order_id: str, symbol: str, side: str,
    requested_qty: Any, request_digest: str, writer_generation: int,
) -> str:
    """Idempotently store a NON-AUTHORIZING order intent (not an order submit)."""
    venue = _token(venue, "venue")
    account = _token(account_fingerprint, "account")
    tenant = _token(tenant_fingerprint, "tenant")
    client_id = _token(client_order_id, "client_order_id")
    symbol = _token(symbol, "symbol")
    if side not in ("buy", "sell"):
        raise ShadowEvidenceError("invalid_side")
    qty = str(_positive(requested_qty))
    digest = _digest(request_digest)
    if type(writer_generation) is not int or writer_generation <= 0:
        raise ShadowEvidenceError("writer_generation_unverified")
    payload = (venue, account, tenant, client_id, symbol, side, qty, digest, writer_generation)
    with _transaction(path) as conn:
        existing = conn.execute(
            """SELECT venue, account_fingerprint, tenant_fingerprint,
               client_order_id, symbol, side, request_qty, request_digest, writer_generation
               FROM shadow_order_intents
               WHERE venue=? AND account_fingerprint=? AND client_order_id=?""",
            (venue, account, client_id),
        ).fetchone()
        if existing is not None:
            if tuple(existing) == payload:
                return "duplicate_intent"
            raise ShadowEvidenceError("conflicting_client_order_id")
        conn.execute(
            """INSERT INTO shadow_order_intents (
               venue, account_fingerprint, tenant_fingerprint, client_order_id,
               symbol, side, request_qty, request_digest, writer_generation
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            payload,
        )
    return "shadow_intent_persisted"


def bind_shadow_broker_ack(
    path: str | Path, *, venue: str, account_fingerprint: str,
    tenant_fingerprint: str, client_order_id: str, broker_order_id: str,
) -> str:
    """Record order ACK identity only. ACK cannot establish a filled trade."""
    venue = _token(venue, "venue")
    account = _token(account_fingerprint, "account")
    tenant = _token(tenant_fingerprint, "tenant")
    client_id = _token(client_order_id, "client_order_id")
    broker_id = _token(broker_order_id, "broker_order_id")
    with _transaction(path) as conn:
        row = conn.execute(
            """SELECT tenant_fingerprint, broker_order_id
               FROM shadow_order_intents
               WHERE venue=? AND account_fingerprint=? AND client_order_id=?""",
            (venue, account, client_id),
        ).fetchone()
        if row is None or row[0] != tenant:
            raise ShadowEvidenceError("unknown_or_cross_tenant_intent")
        if row[1]:
            if row[1] == broker_id:
                return "duplicate_ack"
            raise ShadowEvidenceError("conflicting_broker_order_id")
        try:
            conn.execute(
                """UPDATE shadow_order_intents SET broker_order_id=?
                   WHERE venue=? AND account_fingerprint=? AND client_order_id=?""",
                (broker_id, venue, account, client_id),
            )
        except sqlite3.IntegrityError:
            raise ShadowEvidenceError("broker_order_id_collision") from None
    return "shadow_ack_recorded_not_fill"


def persist_shadow_fill_candidate(
    path: str | Path, *, venue: str, account_fingerprint: str,
    tenant_fingerprint: str, client_order_id: str, broker_order_id: str,
    symbol: str, side: str, execution_id: str, event_digest: str,
    fill_qty: Any, fill_price: Any, cumulative_qty: Any, source: str,
) -> str:
    """Store an idempotent fill CANDIDATE, never a verified execution or ledger post.

    Inputs are supplied by a future broker adapter. This function cannot
    establish source authentication, broker transaction history, or protective
    exit coverage; no trading gate may consume its return status as approval.
    """
    venue = _token(venue, "venue")
    account = _token(account_fingerprint, "account")
    tenant = _token(tenant_fingerprint, "tenant")
    client_id = _token(client_order_id, "client_order_id")
    broker_id = _token(broker_order_id, "broker_order_id")
    symbol = _token(symbol, "symbol")
    exec_id = _token(execution_id, "execution_id")
    digest = _digest(event_digest)
    if side not in ("buy", "sell") or source not in ("private_ws", "authenticated_rest"):
        raise ShadowEvidenceError("invalid_broker_observation")
    qty = _positive(fill_qty)
    price = _positive(fill_price)
    cumulative = _positive(cumulative_qty)
    with _transaction(path) as conn:
        intent = conn.execute(
            """SELECT tenant_fingerprint, symbol, side, request_qty, broker_order_id
               FROM shadow_order_intents
               WHERE venue=? AND account_fingerprint=? AND client_order_id=?""",
            (venue, account, client_id),
        ).fetchone()
        if intent is None or intent[0] != tenant:
            raise ShadowEvidenceError("unknown_or_cross_tenant_intent")
        if (intent[1], intent[2], intent[4]) != (symbol, side, broker_id):
            raise ShadowEvidenceError("broker_order_or_market_mismatch")
        previous = conn.execute(
            """SELECT client_order_id, event_digest FROM shadow_fill_candidates
               WHERE venue=? AND account_fingerprint=? AND execution_id=?""",
            (venue, account, exec_id),
        ).fetchone()
        if previous is not None:
            if previous == (client_id, digest):
                return "duplicate_fill_candidate"
            raise ShadowEvidenceError("conflicting_execution_id")
        filled = conn.execute(
            """SELECT fill_qty FROM shadow_fill_candidates
               WHERE venue=? AND account_fingerprint=? AND client_order_id=?""",
            (venue, account, client_id),
        ).fetchall()
        previously_filled = sum((Decimal(row[0]) for row in filled), Decimal("0"))
        if cumulative != previously_filled + qty:
            raise ShadowEvidenceError("fill_sequence_gap_or_cumulative_mismatch")
        if cumulative > Decimal(intent[3]):
            raise ShadowEvidenceError("overfill_candidate")
        conn.execute(
            """INSERT INTO shadow_fill_candidates (
               venue, account_fingerprint, client_order_id, execution_id,
               event_digest, fill_qty, fill_price, cumulative_qty, source
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (venue, account, client_id, exec_id, digest,
             str(qty), str(price), str(cumulative), source),
        )
    return "fill_candidate_stored_unreconciled"


def shadow_journal_counts(path: str | Path) -> dict[str, Any]:
    """Report only aggregate counts, never account IDs or execution metadata."""
    with _transaction(path) as conn:
        intent_count = conn.execute("SELECT COUNT(*) FROM shadow_order_intents").fetchone()[0]
        fill_count = conn.execute("SELECT COUNT(*) FROM shadow_fill_candidates").fetchone()[0]
    return {
        "shadow_only": True,
        "execution_authority_granted": False,
        "trading_ledger_mutated": False,
        "intents": intent_count,
        "fill_candidates": fill_count,
    }
