"""Pending Kraken confirmed-close audit; never books synthetic realized P&L.

A fill accepted by the canonical v328 verifier may lack a unique existing OPEN
ledger position. Preserve its exact account/order/symbol/side/fee evidence for
manual or independently authenticated replay. These records are NOT positions,
fills independently authenticated by this module, or realized-P&L credits.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.pending_kraken_close_audit_v434")
MARKER = "20261008-pending-kraken-close-audit-v434"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_kraken_closes (
    broker TEXT NOT NULL,
    account_scope TEXT NOT NULL,
    user_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    fill_price REAL NOT NULL,
    filled_usd REAL NOT NULL,
    exit_fee REAL NOT NULL,
    reason TEXT NOT NULL,
    verification_level TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    matched_position_id TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (broker, account_scope, order_id)
)
"""


def _owner(account: Any) -> tuple[str, str]:
    scope = str(account or "").strip()
    if scope.lower() == "platform:kraken":
        return "platform:kraken", "platform"
    parts = scope.split(":")
    if (
        len(parts) == 3 and parts[0].lower() == "user"
        and parts[1].strip() and parts[2].lower() == "kraken"
    ):
        return f"user:{parts[1]}:kraken", parts[1]
    return "", ""


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
        if math.isfinite(number):
            return number
    except (TypeError, ValueError, OverflowError):
        pass
    return None


def record_unmatched_confirmed_close(
    ledger: Any, *, result: Mapping[str, Any], symbol: str, side: str,
    price: float, filled_usd: float, fee: float, reason: str,
) -> bool:
    """Queue exact canonical-final-fill evidence without any P&L side effects."""
    broker = str(result.get("broker") or result.get("venue") or "").strip().lower()
    scope, user_id = _owner(result.get("account") or result.get("account_id"))
    oid = str(result.get("order_id") or result.get("id") or result.get("exchange_order_id") or "").strip()
    direction = str(side or "").strip().lower()
    sym = str(symbol or "").strip().upper()
    values = tuple(map(_finite, (price, filled_usd, fee)))
    if (
        broker != "kraken" or not scope or not oid or not sym
        or direction not in {"buy", "sell"}
        or reason not in {"missing_position", "ambiguous_position", "partial_or_quantity_mismatch"}
        or any(value is None for value in values)
    ):
        return False
    price_f, notional_f, fee_f = values
    if price_f <= 0 or notional_f <= 0 or fee_f < 0:
        return False
    now = datetime.now(timezone.utc).isoformat()
    try:
        with ledger._get_connection() as conn:
            conn.execute(_SCHEMA)
            # A confirmed close already in the canonical ledger must not be
            # counted as pending, including if a recovery event replays.
            if conn.execute(
                "SELECT 1 FROM trade_ledger WHERE order_id = ? AND user_id = ? AND action = 'CLOSE' LIMIT 1",
                (oid, user_id),
            ).fetchone():
                return False
            row = conn.execute(
                """SELECT user_id, symbol, side, fill_price, filled_usd,
                          exit_fee, state
                   FROM pending_kraken_closes
                   WHERE broker = 'kraken' AND account_scope = ? AND order_id = ?""",
                (scope, oid),
            ).fetchone()
            if row:
                same = (
                    row["user_id"] == user_id and row["symbol"] == sym
                    and row["side"] == direction
                    and all(
                        math.isclose(float(row[field]), amount, rel_tol=1e-10, abs_tol=1e-8)
                        for field, amount in (
                            ("fill_price", price_f),
                            ("filled_usd", notional_f),
                            ("exit_fee", fee_f),
                        )
                    )
                )
                if not same:
                    LOGGER.error(
                        "KRAKEN_CLOSE_AUDIT_V434_CONFLICT marker=%s account=%s order_id=%s "
                        "immutable_fill_disagreement=true realized_pnl_unchanged=true",
                        MARKER, scope, oid,
                    )
                    return False
                if row["state"] == "reconciled":
                    return False
                conn.execute(
                    """UPDATE pending_kraken_closes
                       SET seen_count = seen_count + 1, last_seen = ?
                       WHERE broker = 'kraken' AND account_scope = ? AND order_id = ?""",
                    (now, scope, oid),
                )
            else:
                conn.execute(
                    """INSERT INTO pending_kraken_closes
                       (broker, account_scope, user_id, order_id, symbol, side,
                        fill_price, filled_usd, exit_fee, reason, verification_level,
                        state, first_seen, last_seen)
                       VALUES ('kraken', ?, ?, ?, ?, ?, ?, ?, ?, ?,
                               'canonical_v328_fill_fields_only', 'pending', ?, ?)""",
                    (scope, user_id, oid, sym, direction,
                     price_f, notional_f, fee_f, reason, now, now),
                )
        LOGGER.warning(
            "KRAKEN_CLOSE_AUDIT_V434_PENDING marker=%s account=%s order_id=%s "
            "reason=%s independent_entry_unproven=true realized_pnl_not_booked=true "
            "trading_gates_unchanged=true orders_submitted=false",
            MARKER, scope, oid, reason,
        )
        return True
    except Exception as exc:
        LOGGER.warning(
            "KRAKEN_CLOSE_AUDIT_V434_UNAVAILABLE marker=%s reason=%s "
            "realized_pnl_unchanged=true",
            MARKER, type(exc).__name__,
        )
        return False


def mark_reconciled(
    ledger: Any, *, result: Mapping[str, Any], order_id: str, position_id: str,
) -> bool:
    """Mark a previously pending exact fill only after canonical P&L was booked."""
    scope, user_id = _owner(result.get("account") or result.get("account_id"))
    oid, pid = str(order_id or "").strip(), str(position_id or "").strip()
    if not (scope and oid and pid):
        return False
    try:
        with ledger._get_connection() as conn:
            conn.execute(_SCHEMA)
            # The canonical CLOSE transaction and completed trade must exist.
            recorded = conn.execute(
                """SELECT 1 FROM trade_ledger l
                   INNER JOIN completed_trades c
                     ON c.position_id = l.position_id AND c.user_id = l.user_id
                   WHERE l.action = 'CLOSE' AND l.order_id = ?
                     AND l.position_id = ? AND l.user_id = ?
                     AND c.exit_reason = 'canonical_confirmed_fill' LIMIT 1""",
                (oid, pid, user_id),
            ).fetchone()
            if not recorded:
                return False
            changed = conn.execute(
                """UPDATE pending_kraken_closes
                   SET state='reconciled', matched_position_id=?, last_seen=?
                   WHERE broker='kraken' AND account_scope=? AND order_id=?
                     AND user_id=? AND state='pending'""",
                (pid, datetime.now(timezone.utc).isoformat(), scope, oid, user_id),
            )
            return changed.rowcount > 0
    except Exception as exc:
        LOGGER.warning("KRAKEN_CLOSE_AUDIT_V434_RESOLVE_ERROR reason=%s", type(exc).__name__)
        return False


def pending_summary(ledger: Any, *, account_scope: str) -> dict[str, Any]:
    """Read-only count for an explicitly requested authenticated account scope."""
    scope, _ = _owner(account_scope)
    if not scope:
        raise ValueError("explicit Kraken account scope required")
    with ledger._get_connection() as conn:
        conn.execute(_SCHEMA)
        rows = conn.execute(
            """SELECT reason, COUNT(*) AS trades
               FROM pending_kraken_closes
               WHERE account_scope=? AND state='pending'
               GROUP BY reason""",
            (scope,),
        ).fetchall()
    buckets = {str(r["reason"]): int(r["trades"]) for r in rows}
    return {"account_scope": scope, "pending_confirmed_closes": sum(buckets.values()),
            "reasons": buckets, "realized_pnl_from_pending_usd": None,
            "historical_reconstruction_proven": False}


__all__ = ["record_unmatched_confirmed_close", "mark_reconciled", "pending_summary"]
