"""Authoritative confirmed-fill -> realized P&L reconciliation v412.

This patch bridges NIJA's existing confirmed-fill truth path (v328/v346) to the
existing position-close P&L ledger.  It never infers a close from an ACK, quote,
requested size, or market price.  A realized trade is booked only when:

* v328 has already accepted a real final fill;
* the fill side closes exactly one matching open ledger position;
* the confirmed fill quantity matches the whole open position (partial fills are
  left pending rather than overstating P&L);
* entry price/size are positive in the existing ledger; and
* an explicit exit fee/commission is present in the exchange result.

Repeated recovery of the same exchange order is idempotent by order_id.  This
module changes no strategy, risk, writer, nonce, capital, position-sync, exit,
kill-switch, minimum-order, or activation gate and submits/cancels no orders.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_realized_pnl_reconciliation_v412")
MARKER = "20260909-runtime-realized-pnl-reconciliation-v412"
_READY_FLAG = "NIJA_REALIZED_PNL_RECONCILIATION_V412_READY"
_PATCH_ATTR = "_nija_realized_pnl_reconciliation_v412"
_LOCK = threading.RLock()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _symbol_key(value: Any) -> str:
    raw = str(value or "").strip().upper().split(":", 1)[0]
    compact = "".join(ch for ch in raw if ch.isalnum())
    aliases = {
        "XETHZUSD": "ETHUSD",
        "ETHUSD": "ETHUSD",
        "XXBTZUSD": "BTCUSD",
        "XBTUSD": "BTCUSD",
        "BTCUSD": "BTCUSD",
    }
    return aliases.get(compact, compact)


def _norm_side(value: Any) -> str:
    return str(value or "").strip().lower()


def _order_id(result: Mapping[str, Any]) -> str:
    return str(
        result.get("order_id")
        or result.get("id")
        or result.get("exchange_order_id")
        or result.get("txid")
        or ""
    ).strip()


def _explicit_fee(result: Mapping[str, Any]) -> tuple[bool, float]:
    for key in ("fee", "fees", "fill_fee", "filled_fee", "commission", "commission_usd"):
        if key not in result:
            continue
        value = result.get(key)
        if isinstance(value, Mapping):
            for nested in ("usd", "amount", "cost", "value"):
                if nested in value:
                    fee = _f(value.get(nested), -1.0)
                    return (fee >= 0.0), max(0.0, fee)
            return False, 0.0
        fee = _f(value, -1.0)
        return (fee >= 0.0), max(0.0, fee)
    return False, 0.0


def _candidate_user(result: Mapping[str, Any]) -> str:
    """Map authenticated account routing identity to the ledger's user_id.

    The ledger stores the platform owner as "platform", not "platform:kraken".
    An opaque broker account id is not evidence of a ledger user.  Prefer an
    explicit account-scoped identity to an unscoped user hint, and fail closed
    (no matching ledger position) when a supplied identity is unrecognized.
    """
    for key in ("account", "account_id", "account_key", "user_id", "owner_id"):
        raw = str(result.get(key) or "").strip()
        if not raw:
            continue
        lowered = raw.lower()
        if lowered in {"platform", "master"} or lowered.startswith("platform:"):
            return "platform"
        if lowered.startswith("user:"):
            parts = raw.split(":")
            return parts[1].strip() if len(parts) >= 2 and parts[1].strip() else "__unresolved_account_identity__"
        if key in {"user_id", "owner_id"}:
            return raw
        # An opaque account identifier must not be treated as a user_id.
        return "__unresolved_account_identity__"
    return "__unresolved_account_identity__"


def _ledger() -> Any:
    pnl_patch = importlib.import_module("bot.position_close_pnl_runtime_patch")
    hook = getattr(pnl_patch, "install_import_hook", None)
    if callable(hook):
        hook()
    try:
        module = importlib.import_module("bot.trade_ledger_db")
    except Exception:
        module = importlib.import_module("trade_ledger_db")
    getter = getattr(module, "get_trade_ledger_db", None)
    if not callable(getter):
        raise RuntimeError("trade_ledger_singleton_missing")
    return getter()


def _kraken_account_scope(result: Mapping[str, Any]) -> str:
    """An authenticated Kraken fill must name exactly one Kraken account."""
    value = str(result.get("account") or result.get("account_id") or "").strip()
    if value.lower() == "platform:kraken":
        return "platform:kraken"
    parts = value.split(":")
    if (
        len(parts) == 3 and parts[0].lower() == "user"
        and parts[1].strip() and parts[2].lower() == "kraken"
    ):
        return f"user:{parts[1]}:kraken"
    return ""


def _already_booked(
    ledger: Any, order_id: str, *, user_id: str = "", broker: str = "",
) -> bool:
    if not order_id:
        return False
    with ledger._get_connection() as conn:
        cur = conn.cursor()
        if broker == "kraken" and user_id:
            cur.execute(
                """SELECT 1 FROM trade_ledger WHERE order_id = ? AND user_id = ?
                   AND action = 'CLOSE' AND notes LIKE ? LIMIT 1""",
                (order_id, user_id, "%; broker=kraken; %"),
            )
        else:
            # Legacy/non-Kraken handling remains conservative and unchanged.
            cur.execute(
                "SELECT 1 FROM trade_ledger WHERE order_id = ? AND action = 'CLOSE' LIMIT 1",
                (order_id,),
            )
        return cur.fetchone() is not None


def _authenticated_kraken_open_position(
    conn: Any, position: Mapping[str, Any], *, account_scope: str,
) -> bool:
    """No exact QueryOrders OPEN identity = no Kraken realized P&L."""
    position_id = str(position.get("position_id") or "")
    owner = str(position.get("user_id") or "")
    if not position_id or not owner or not account_scope:
        return False
    entries = conn.execute(
        """SELECT order_id, symbol, side, price, quantity, size_usd, fee, notes
           FROM trade_ledger WHERE position_id = ? AND user_id = ?
           AND action = 'OPEN'""",
        (position_id, owner),
    ).fetchall()
    if len(entries) != 1:
        return False
    opened = entries[0]
    notes = str(opened["notes"] or "")
    order_id = str(opened["order_id"] or "")
    if not order_id or not notes.startswith("authenticated_kraken_queryorders_entry; "):
        return False
    parts = notes.split("; ")
    if f"order_id={order_id}" not in parts or f"account={account_scope}" not in parts:
        return False
    direction = _norm_side(position.get("side"))
    if not (
        (direction in {"long", "buy"} and opened["side"] == "BUY")
        or (direction in {"short", "sell"} and opened["side"] == "SELL")
    ):
        return False
    if _symbol_key(opened["symbol"]) != _symbol_key(position.get("symbol")):
        return False
    for left, right in (
        (opened["price"], position.get("entry_price")),
        (opened["quantity"], position.get("quantity")),
        (opened["size_usd"], position.get("size_usd")),
        (opened["fee"], position.get("entry_fee")),
    ):
        lf = _f(left, -1.0)
        rf = _f(right, -1.0)
        if lf < 0 or rf < 0 or not math.isclose(lf, rf, rel_tol=1e-10, abs_tol=1e-9):
            return False
    return True


def _matching_positions(
    ledger: Any, symbol: str, side: str, user_hint: str, *,
    broker: str = "", account_scope: str = "", position_id_hint: str = "",
) -> list[dict[str, Any]]:
    wanted = _symbol_key(symbol)
    closing_long = _norm_side(side) in {"sell", "short"}
    closing_short = _norm_side(side) in {"buy", "cover"}
    if not (closing_long or closing_short):
        return []
    out: list[dict[str, Any]] = []
    with ledger._get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM open_positions WHERE status = 'open' ORDER BY entry_time DESC")
        rows = [dict(row) for row in cur.fetchall()]
        for row in rows:
            if _symbol_key(row.get("symbol")) != wanted:
                continue
            pos_side = _norm_side(row.get("side"))
            if closing_long and pos_side not in {"long", "buy"}:
                continue
            if closing_short and pos_side not in {"short", "sell"}:
                continue
            if user_hint and str(row.get("user_id") or "").strip() != user_hint:
                continue
            if position_id_hint and str(row.get("position_id") or "") != position_id_hint:
                continue
            if broker == "kraken":
                if not account_scope or not _authenticated_kraken_open_position(
                    conn, row, account_scope=account_scope
                ):
                    continue
            elif str(row.get("notes") or "").startswith("authenticated_kraken_queryorders_entry; "):
                # A Kraken-authenticated opening may not close from another venue.
                continue
            out.append(row)
    return out


def _audit_deferred_close(
    ledger: Any, result: Mapping[str, Any], *, symbol: str, side: str,
    fill_price: float, filled_usd: float, exit_fee: float, reason: str,
) -> None:
    """Audit only a canonical verified final fill with no safe ledger match.

    Failure to persist an audit record cannot promote realized P&L or change
    execution readiness. The queue is account-scoped and never guesses entry.
    """
    try:
        from bot.pending_kraken_close_audit_v434 import record_unmatched_confirmed_close
        record_unmatched_confirmed_close(
            ledger, result=result, symbol=symbol, side=side,
            price=fill_price, filled_usd=filled_usd, fee=exit_fee, reason=reason,
        )
    except Exception as exc:
        LOGGER.warning(
            "REALIZED_PNL_V434_AUDIT_DEFERRED exception_type=%s pnl_not_booked=true",
            type(exc).__name__,
        )


def _reconcile_confirmed_fill(
    result: Mapping[str, Any], *, symbol: str, side: str, fill_price: float, filled_usd: float
) -> None:
    oid = _order_id(result)
    if not oid:
        return
    try:
        broker = str(result.get("broker") or result.get("venue") or result.get("exchange") or "").strip().lower()
        account_scope = _kraken_account_scope(result)
        if broker == "kraken" and not account_scope:
            LOGGER.warning(
                "REALIZED_PNL_V435_PENDING marker=%s order_id=%s "
                "reason=exact_kraken_account_scope_unproven realized_pnl_not_booked=true",
                MARKER, oid,
            )
            return
        ledger = _ledger()
        user_hint = _candidate_user(result)
        if user_hint == "__unresolved_account_identity__":
            LOGGER.warning(
                "REALIZED_PNL_V412_PENDING marker=%s order_id=%s symbol=%s "
                "reason=authenticated_account_scope_unproven "
                "realized_net_pnl_not_booked=true cross_account_booking_forbidden=true",
                MARKER, oid, symbol,
            )
            return
        if _already_booked(ledger, oid, user_id=user_hint, broker=broker):
            LOGGER.info(
                "REALIZED_PNL_V412_DUPLICATE_IGNORED marker=%s order_id=%s symbol=%s idempotent=true",
                MARKER, oid, symbol,
            )
            return

        fee_known, exit_fee = _explicit_fee(result)
        if not fee_known:
            LOGGER.warning(
                "REALIZED_PNL_V412_PENDING marker=%s order_id=%s symbol=%s reason=exit_fee_unproven "
                "realized_net_pnl_not_booked=true fill_confirmed=true",
                MARKER, oid, symbol,
            )
            return

        candidates = _matching_positions(
            ledger, symbol, side, user_hint, broker=broker, account_scope=account_scope,
            position_id_hint=str(result.get("opening_position_id") or result.get("position_id") or "").strip(),
        )
        if len(candidates) != 1:
            LOGGER.warning(
                "REALIZED_PNL_V412_PENDING marker=%s order_id=%s symbol=%s reason=position_match_count_%s "
                "user_hint=%s realized_net_pnl_not_booked=true fill_confirmed=true",
                MARKER, oid, symbol, len(candidates), user_hint or "none",
            )
            _audit_deferred_close(
                ledger, result, symbol=symbol, side=side, fill_price=fill_price,
                filled_usd=filled_usd, exit_fee=exit_fee,
                reason="missing_position" if not candidates else "ambiguous_position",
            )
            return

        pos = candidates[0]
        entry_price = _f(pos.get("entry_price"))
        size_usd = _f(pos.get("size_usd"))
        position_qty = abs(_f(pos.get("quantity")))
        fill_qty = abs(_f(filled_usd) / _f(fill_price)) if _f(fill_price) > 0 else 0.0
        if entry_price <= 0.0 or size_usd <= 0.0 or position_qty <= 0.0 or fill_qty <= 0.0:
            LOGGER.warning(
                "REALIZED_PNL_V412_PENDING marker=%s order_id=%s symbol=%s reason=invalid_cost_or_quantity "
                "realized_net_pnl_not_booked=true",
                MARKER, oid, symbol,
            )
            return

        tolerance = max(1e-8, position_qty * 0.005)
        if abs(fill_qty - position_qty) > tolerance:
            LOGGER.warning(
                "REALIZED_PNL_V412_PENDING marker=%s order_id=%s symbol=%s reason=partial_or_quantity_mismatch "
                "position_qty=%.12f fill_qty=%.12f tolerance=%.12f realized_net_pnl_not_booked=true",
                MARKER, oid, symbol, position_qty, fill_qty, tolerance,
            )
            _audit_deferred_close(
                ledger, result, symbol=symbol, side=side, fill_price=fill_price,
                filled_usd=filled_usd, exit_fee=exit_fee,
                reason="partial_or_quantity_mismatch",
            )
            return

        close = getattr(ledger, "close_position_with_pnl", None)
        if not callable(close):
            raise RuntimeError("close_position_with_pnl_missing")
        pnl = close(
            position_id=str(pos.get("position_id") or ""),
            symbol=str(pos.get("symbol") or symbol),
            user_id=str(pos.get("user_id") or "platform"),
            exit_price=float(fill_price),
            exit_fee=float(exit_fee),
            exit_reason="canonical_confirmed_fill",
            order_id=oid,
            broker=broker,
        )
        if not bool(pnl.get("success")):
            LOGGER.error(
                "REALIZED_PNL_V412_BOOK_FAILED marker=%s order_id=%s symbol=%s error=%s fill_confirmed=true",
                MARKER, oid, symbol, str(pnl.get("error") or "unknown"),
            )
            return
        # A previous pending audit record may be resolved only after the
        # canonical transaction and completed trade are both present.
        try:
            from bot.pending_kraken_close_audit_v434 import mark_reconciled
            mark_reconciled(
                ledger, result=result, order_id=oid,
                position_id=str(pnl.get("position_id") or ""),
            )
        except Exception as audit_exc:
            LOGGER.warning(
                "REALIZED_PNL_V434_PENDING_CLOSE_RESOLVE_DEFERRED exception_type=%s",
                type(audit_exc).__name__,
            )
        # Read the canonical ledger directly; never feed speculative ACKs or a
        # shared cross-account singleton into adaptive position sizing.
        try:
            from bot.confirmed_performance_report import log_confirmed_performance

            log_confirmed_performance(ledger, broker=broker, user_id=user_hint)
        except Exception as report_exc:
            LOGGER.warning("CONFIRMED_PERFORMANCE_HOOK_UNAVAILABLE error=%s", type(report_exc).__name__)
        LOGGER.critical(
            "REALIZED_PNL_V412_BOOKED marker=%s order_id=%s position_id=%s user_id=%s symbol=%s "
            "entry_price=%.10f exit_price=%.10f quantity=%.12f entry_fee=%.8f exit_fee=%.8f "
            "gross_pnl=%.8f net_pnl=%.8f pnl_pct=%+.6f broker=%s fill_confirmed=true "
            "fees_proven=true duplicate=false",
            MARKER, oid, str(pnl.get("position_id") or ""), str(pnl.get("user_id") or "platform"),
            str(pnl.get("symbol") or symbol), _f(pnl.get("entry_price")), _f(pnl.get("exit_price")),
            _f(pnl.get("quantity")), _f(pnl.get("entry_fee")), _f(pnl.get("exit_fee")),
            _f(pnl.get("gross_profit")), _f(pnl.get("net_profit")), _f(pnl.get("profit_pct")),
            broker or "unknown",
        )
    except Exception as exc:
        LOGGER.exception(
            "REALIZED_PNL_V412_RECONCILE_ERROR marker=%s order_id=%s symbol=%s error=%s:%s "
            "fill_proof_unchanged=true trading_gates_unchanged=true",
            MARKER, oid, symbol, type(exc).__name__, exc,
        )


def install() -> bool:
    with _LOCK:
        try:
            module = importlib.import_module("bot.runtime_confirmed_fill_profitability_v328_patch")
            current = getattr(module, "_normalize_dict_fill", None)
            if not callable(current):
                os.environ[_READY_FLAG] = "0"
                return False
            if getattr(current, _PATCH_ATTR, False):
                os.environ[_READY_FLAG] = "1"
                return True

            @wraps(current)
            def normalize_v412(result: Mapping[str, Any], *, symbol: str, side: str):
                price, filled_usd = current(result, symbol=symbol, side=side)
                # The wrapped v328/v346 function has already established real
                # confirmed-fill truth at this point.  Accounting is best-effort
                # and never changes the execution result or trading authority.
                _reconcile_confirmed_fill(
                    result,
                    symbol=symbol,
                    side=side,
                    fill_price=float(price),
                    filled_usd=float(filled_usd),
                )
                return price, filled_usd

            setattr(normalize_v412, _PATCH_ATTR, True)
            setattr(normalize_v412, "__wrapped__", current)
            module._normalize_dict_fill = normalize_v412
            os.environ[_READY_FLAG] = "1"
            LOGGER.critical(
                "REALIZED_PNL_V412_READY marker=%s ready=true confirmed_fill_required=true full_close_required=true "
                "explicit_exit_fee_required=true unique_position_match_required=true idempotent_order_id=true "
                "partial_fill_not_closed=true pnl_fabricated=false orders_submitted=false orders_cancelled=false "
                "risk_strategy_writer_nonce_capital_position_exit_killswitch_activation_gates_unchanged=true "
                "safety_gates_bypassed=false",
                MARKER,
            )
            return True
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.exception(
                "REALIZED_PNL_V412_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
            return False


install_import_hook = install

__all__ = ["MARKER", "install", "install_import_hook"]
