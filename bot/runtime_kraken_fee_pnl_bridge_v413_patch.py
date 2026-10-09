"""Authenticated Kraken fee -> realized P&L bridge v413.

This patch fixes two accounting-provenance gaps without changing trading logic:
1) exact authenticated Kraken QueryOrders rows used for opening-order proof keep
   their fee metadata and are explicitly tagged as entry proofs;
2) confirmed Kraken fills that reach v412 without a fee are enriched only by an
   exact authenticated QueryOrders match for that order id before realized P&L
   accounting proceeds.

Known opening-order replays are ignored by realized-P&L accounting. No fee is
estimated, no fill is fabricated, and no order/risk/writer/nonce/capital/
position/kill-switch/activation behavior is changed.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_fee_pnl_bridge_v413")
MARKER = "20260910-runtime-kraken-fee-pnl-bridge-v413"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_FEE_PNL_BRIDGE_V413_READY"
_PATCH_ATTR = "_nija_runtime_kraken_fee_pnl_bridge_v413"
_LOCK = threading.RLock()
_FEE_CACHE: dict[tuple[str, str], tuple[float, str]] = {}
_FINAL = {"closed", "filled", "complete", "completed", "executed"}


def _f(value: Any, default: float = -1.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _order_id(result: Mapping[str, Any]) -> str:
    return str(result.get("order_id") or result.get("id") or result.get("exchange_order_id") or result.get("txid") or "").strip()


def _has_explicit_fee(result: Mapping[str, Any]) -> bool:
    for key in ("fee", "fees", "fill_fee", "filled_fee", "commission", "commission_usd"):
        if key not in result:
            continue
        value = result.get(key)
        if isinstance(value, Mapping):
            for nested in ("usd", "amount", "cost", "value"):
                if nested in value and _f(value.get(nested)) >= 0.0:
                    return True
        elif _f(value) >= 0.0:
            return True
    return False


def _is_opening_proof(result: Mapping[str, Any]) -> bool:
    role = str(result.get("execution_role") or result.get("fill_role") or "").strip().lower()
    if role in {"entry", "open", "opening"}:
        return True
    return bool(
        result.get("authenticated_kraken_opening_order") is True
        or (
            result.get("authenticated_kraken_queryorders") is True
            and str(result.get("opening_position_id") or "").strip()
        )
    )


def _ledger_user_id(result: Mapping[str, Any]) -> str:
    """Return a ledger user only for a proven, scoped Kraken account.

    Do not silently attribute account-less or opaque authenticated fills to
    the platform; an additional user Kraken account can hold the same symbol.
    """
    raw = str(result.get("account") or result.get("account_id") or "").strip()
    lowered = raw.lower()
    if lowered in {"platform", "master", "platform:kraken"}:
        return "platform"
    if lowered.startswith("user:") and lowered.endswith(":kraken"):
        parts = raw.split(":")
        if len(parts) == 3 and parts[1].strip():
            return parts[1].strip()
    return ""


def _account_owner(result: Mapping[str, Any]) -> str:
    """Canonical owner for comparing independent proof and fill provenance."""
    return _ledger_user_id(result)

def _exact_kraken_account_scope(result: Mapping[str, Any]) -> str:
    """Require a specific Kraken account, never infer from a different broker."""
    raw = str(result.get("account") or result.get("account_id") or "").strip()
    if raw.lower() == "platform:kraken":
        return "platform:kraken"
    parts = raw.split(":")
    if len(parts) == 3 and parts[0].lower() == "user" and parts[1].strip() and parts[2].lower() == "kraken":
        return f"user:{parts[1]}:kraken"
    return ""



def _ensure_opening_cost_basis(
    result: Mapping[str, Any], *, symbol: str, side: str, fill_price: float, filled_usd: float
) -> None:
    """Persist authenticated Kraken entry cost basis for later realized P&L.

    This is accounting-only. It never creates broker positions or submits orders.
    The source must already be an authenticated exact QueryOrders opening proof.
    """
    # An "entry" role is a routing hint, not authenticated exchange evidence.
    # Only the v372 exact QueryOrders final-fill proof may write opening basis.
    if not (
        result.get("authenticated_kraken_queryorders") is True
        and result.get("authenticated_kraken_opening_order") is True
        and str(result.get("broker") or "kraken").strip().lower() == "kraken"
    ):
        LOGGER.warning(
            "REALIZED_PNL_V435_ENTRY_REJECTED marker=%s "
            "reason=authenticated_exact_opening_proof_missing "
            "cost_basis_not_booked=true execution_authority_unchanged=true",
            MARKER,
        )
        return
    position_id = str(result.get("opening_position_id") or "").strip()
    order_id = _order_id(result)
    if not position_id or not order_id or fill_price <= 0.0 or filled_usd <= 0.0:
        LOGGER.warning(
            "REALIZED_PNL_V413_ENTRY_LEDGER_PENDING marker=%s order_id=%s symbol=%s "
            "reason=missing_position_or_fill_truth cost_basis_fabricated=false",
            MARKER, order_id or "unknown", symbol,
        )
        return

    fee_known = _has_explicit_fee(result)
    if not fee_known:
        LOGGER.warning(
            "REALIZED_PNL_V413_ENTRY_LEDGER_PENDING marker=%s order_id=%s symbol=%s "
            "reason=entry_fee_unproven cost_basis_fabricated=false",
            MARKER, order_id, symbol,
        )
        return

    fee = 0.0
    for key in ("fee", "fees", "fill_fee", "filled_fee", "commission", "commission_usd"):
        if key not in result:
            continue
        value = result.get(key)
        if isinstance(value, Mapping):
            for nested in ("usd", "amount", "cost", "value"):
                if nested in value and _f(value.get(nested)) >= 0.0:
                    fee = max(0.0, _f(value.get(nested), 0.0))
                    break
        elif _f(value) >= 0.0:
            fee = max(0.0, _f(value, 0.0))
        break

    try:
        try:
            ledger_module = importlib.import_module("bot.trade_ledger_db")
        except Exception:
            ledger_module = importlib.import_module("trade_ledger_db")
        getter = getattr(ledger_module, "get_trade_ledger_db", None)
        if not callable(getter):
            raise RuntimeError("trade_ledger_singleton_missing")
        ledger = getter()

        # This module must not split OPEN transaction and open_positions into
        # two commits: a crash between those writes creates an orphaned fill.
        # SHORT entry SELL is an OPEN, not the legacy record_sell() CLOSE action.
        quantity = float(filled_usd) / float(fill_price)
        user_id = _ledger_user_id(result)
        if not user_id:
            LOGGER.warning(
                "REALIZED_PNL_V413_ENTRY_LEDGER_PENDING marker=%s order_id=%s position_id=%s "
                "reason=authenticated_account_scope_unproven ledger_user_guessed=false",
                MARKER, order_id, position_id,
            )
            return
        side_norm = str(side or "").strip().lower()
        if side_norm not in {"buy", "sell"}:
            raise ValueError("entry_side_not_authenticated")
        position_side = "LONG" if side_norm == "buy" else "SHORT"
        notes = (
            "authenticated_kraken_queryorders_entry; "
            f"order_id={order_id}; account={str(result.get('account') or result.get('account_id') or '')}"
        )
        atomic_book = getattr(ledger, "record_confirmed_entry_atomic", None)
        if not callable(atomic_book):
            raise RuntimeError("atomic_confirmed_entry_writer_missing")
        opened = atomic_book(
            position_id=position_id,
            order_id=order_id,
            user_id=user_id,
            symbol=symbol,
            side=position_side,
            entry_price=float(fill_price),
            quantity=quantity,
            size_usd=float(filled_usd),
            entry_fee=fee,
            notes=notes,
        )
        if opened:
            LOGGER.critical(
                "REALIZED_PNL_V413_ENTRY_LEDGER_BOOKED marker=%s order_id=%s position_id=%s user_id=%s "
                "symbol=%s side=%s entry_price=%.10f quantity=%.12f size_usd=%.8f entry_fee=%.8f "
                "source=authenticated_kraken_queryorders cost_basis_fabricated=false orders_submitted=false",
                MARKER, order_id, position_id, user_id, symbol, position_side,
                float(fill_price), quantity, float(filled_usd), fee,
            )
    except Exception as exc:
        LOGGER.exception(
            "REALIZED_PNL_V413_ENTRY_LEDGER_ERROR marker=%s order_id=%s position_id=%s symbol=%s "
            "error=%s:%s cost_basis_fabricated=false trading_gates_unchanged=true",
            MARKER, order_id or "unknown", position_id or "unknown", symbol, type(exc).__name__, exc,
        )


def _canonical_symbol(value: Any) -> str:
    try:
        v366 = importlib.import_module("bot.runtime_kraken_margin_canonical_coverage_v366_patch")
        fn = getattr(v366, "canonical_symbol", None)
        if callable(fn):
            return str(fn(value) or "").strip().upper()
    except Exception:
        pass
    return str(value or "").strip().upper()


def _pair_identity(value: Any) -> str:
    """Normalize Kraken legacy pair aliases and routed suffixes for comparison."""
    core = str(value or "").strip().upper().split(":", 1)[0]
    if not core:
        return ""
    canon = _canonical_symbol(core)
    compact = "".join(char for char in str(canon) if char.isalnum())
    return {
        "XXBTZUSD": "BTCUSD", "XBTUSD": "BTCUSD",
        "XETHZUSD": "ETHUSD",
    }.get(compact, compact)


def _query_exact_fee(
    order_id: str, symbol: str, side: str, *, account_scope: str = "",
) -> tuple[dict[str, Any] | None, str]:
    """Fetch exact authenticated fee only from the requested Kraken account.

    A global order-id cache or a cross-user QueryOrders scan can misattribute
    executions. No fallback to a different account is permitted.
    """
    account = _exact_kraken_account_scope({"account": account_scope})
    if not account:
        return None, "exact_kraken_account_scope_unproven"
    key = (account, str(order_id or "").strip())
    cached = _FEE_CACHE.get(key)
    if cached is not None:
        fee, cached_account = cached
        if cached_account != account:
            return None, "cached_account_scope_conflict"
        return {"fee": fee, "broker": "kraken",
                "fee_source": "authenticated_kraken_queryorders",
                "account": account}, "cache"
    try:
        v367 = importlib.import_module("bot.runtime_kraken_margin_protection_truth_v367_patch")
        brokers_fn = getattr(v367, "_account_brokers", None)
        private_call_fn = getattr(v367, "_private_call", None)
        if not callable(brokers_fn) or not callable(private_call_fn):
            return None, "kraken_authenticated_queryorders_unavailable"
        matched_brokers = [
            broker for broker_account, broker in list(brokers_fn() or [])
            if str(broker_account or "").strip() == account
        ]
        if len(matched_brokers) != 1:
            return None, "exact_account_broker_missing_or_ambiguous"
        call = private_call_fn(matched_brokers[0])
        if not callable(call):
            return None, "exact_account_private_reader_unavailable"
        try:
            payload = call("QueryOrders", {"txid": order_id, "trades": "true"})
        except Exception as exc:
            return None, f"queryorders_private_exception:{type(exc).__name__}"
        if not isinstance(payload, Mapping) or payload.get("error"):
            return None, "queryorders_authenticated_response_unproven"
        rows = payload.get("result")
        if not isinstance(rows, Mapping):
            return None, "queryorders_result_unproven"
        row = rows.get(order_id)
        if not isinstance(row, Mapping):
            return None, "exact_order_not_found"
        status = str(row.get("status") or "").strip().lower()
        if status not in _FINAL:
            return None, "exact_order_not_final"
        vol_exec = _f(row.get("vol_exec"), 0.0)
        cost = _f(row.get("cost"), 0.0)
        fee = _f(row.get("fee"))
        if vol_exec <= 0 or cost <= 0 or fee < 0:
            return None, "exact_order_fill_cost_fee_unproven"
        descr = row.get("descr") if isinstance(row.get("descr"), Mapping) else {}
        row_symbol = _pair_identity(descr.get("pair"))
        wanted_symbol = _pair_identity(symbol)
        row_side = str(descr.get("type") or "").strip().lower()
        wanted_side = str(side or "").strip().lower()
        if not row_symbol or not wanted_symbol or row_symbol != wanted_symbol:
            return None, "exact_order_symbol_unproven"
        if row_side not in {"buy", "sell"} or wanted_side != row_side:
            return None, "exact_order_side_mismatch"
        _FEE_CACHE[key] = (float(fee), account)
        return {
            "fee": float(fee), "broker": "kraken",
            "fee_source": "authenticated_kraken_queryorders",
            "account": account,
        }, "authenticated_exact_match"
    except Exception as exc:
        return None, f"queryorders_exception:{type(exc).__name__}"


def _patch_v372_opening_proof() -> bool:
    try:
        module = importlib.import_module("bot.runtime_kraken_margin_execution_proof_liveness_v372_patch")
        current = getattr(module, "_exact_queryorders_fill", None)
        if not callable(current):
            return False
        if getattr(current, _PATCH_ATTR, False):
            return True

        @wraps(current)
        def exact_with_fee(call: Any, opening: Mapping[str, Any]):
            captured: dict[str, Any] = {}

            def capture(endpoint: str, params: Any):
                payload = call(endpoint, params)
                if endpoint == "QueryOrders" and isinstance(payload, Mapping):
                    captured["payload"] = payload
                return payload

            proof, reason = current(capture, opening)
            if isinstance(proof, dict):
                proof["execution_role"] = "entry"
                proof["authenticated_kraken_opening_order"] = True
                oid = _order_id(proof)
                payload = captured.get("payload")
                rows = payload.get("result") if isinstance(payload, Mapping) else None
                row = rows.get(oid) if isinstance(rows, Mapping) else None
                if isinstance(row, Mapping) and "fee" in row:
                    fee = _f(row.get("fee"))
                    if fee >= 0.0:
                        proof["fee"] = float(fee)
                        proof["fee_source"] = "authenticated_kraken_queryorders"
            return proof, reason

        setattr(exact_with_fee, _PATCH_ATTR, True)
        setattr(exact_with_fee, "__wrapped__", current)
        module._exact_queryorders_fill = exact_with_fee
        return True
    except Exception:
        LOGGER.exception("KRAKEN_FEE_PNL_V413_V372_PATCH_ERROR marker=%s fail_closed=true", MARKER)
        return False


def _patch_v412_reconcile() -> bool:
    try:
        module = importlib.import_module("bot.runtime_realized_pnl_reconciliation_v412_patch")
        current = getattr(module, "_reconcile_confirmed_fill", None)
        if not callable(current):
            return False
        if getattr(current, _PATCH_ATTR, False):
            return True

        @wraps(current)
        def reconcile_v413(result: Mapping[str, Any], *, symbol: str, side: str, fill_price: float, filled_usd: float) -> None:
            oid = _order_id(result)
            if _is_opening_proof(result):
                _ensure_opening_cost_basis(
                    result,
                    symbol=symbol,
                    side=side,
                    fill_price=float(fill_price),
                    filled_usd=float(filled_usd),
                )
                LOGGER.info(
                    "REALIZED_PNL_V413_NONCLOSE_IGNORED marker=%s order_id=%s symbol=%s role=entry "
                    "opening_order_replay=true realized_pnl_unchanged=true cost_basis_checked=true",
                    MARKER, oid or "unknown", symbol,
                )
                return
            enriched = dict(result)
            if not _has_explicit_fee(enriched) and oid:
                fee_meta, reason = _query_exact_fee(
                    oid, symbol, side,
                    account_scope=_exact_kraken_account_scope(enriched),
                )
                if fee_meta:
                    explicit_owner = _account_owner(enriched)
                    authenticated_owner = _account_owner(fee_meta)
                    if explicit_owner and explicit_owner != authenticated_owner:
                        LOGGER.error(
                            "REALIZED_PNL_V413_ACCOUNT_MISMATCH marker=%s order_id=%s symbol=%s "
                            "authenticated_fee_owner_conflicts_with_fill=true "
                            "realized_pnl_not_booked=true account_isolation_preserved=true",
                            MARKER, oid, symbol,
                        )
                        return
                    enriched.update(fee_meta)
                    LOGGER.critical(
                        "REALIZED_PNL_V413_FEE_RESOLVED marker=%s order_id=%s symbol=%s fee=%.8f source=authenticated_kraken_queryorders exact_order_match=true fee_estimated=false",
                        MARKER, oid, symbol, float(enriched.get("fee", 0.0)),
                    )
                else:
                    LOGGER.warning(
                        "REALIZED_PNL_V413_FEE_PENDING marker=%s order_id=%s symbol=%s reason=%s fee_estimated=false realized_pnl_not_fabricated=true",
                        MARKER, oid, symbol, reason,
                    )
            return current(enriched, symbol=symbol, side=side, fill_price=fill_price, filled_usd=filled_usd)

        setattr(reconcile_v413, _PATCH_ATTR, True)
        setattr(reconcile_v413, "__wrapped__", current)
        module._reconcile_confirmed_fill = reconcile_v413
        return True
    except Exception:
        LOGGER.exception("KRAKEN_FEE_PNL_V413_V412_PATCH_ERROR marker=%s fail_closed=true", MARKER)
        return False


def install() -> bool:
    with _LOCK:
        v372 = _patch_v372_opening_proof()
        v412 = _patch_v412_reconcile()
        ready = bool(v372 and v412)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        (LOGGER.critical if ready else LOGGER.error)(
            "KRAKEN_FEE_PNL_V413_%s marker=%s ready=%s authenticated_queryorders_fee_only=true exact_order_match_required=true opening_replays_ignored=true fee_estimated=false orders_submitted=false orders_cancelled=false strategy_risk_writer_nonce_capital_position_killswitch_activation_gates_unchanged=true safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready


install_import_hook = install

__all__ = ["MARKER", "install", "install_import_hook"]
