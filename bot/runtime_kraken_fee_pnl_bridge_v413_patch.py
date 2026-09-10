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
_FEE_CACHE: dict[str, tuple[float, str]] = {}
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


def _canonical_symbol(value: Any) -> str:
    try:
        v366 = importlib.import_module("bot.runtime_kraken_margin_canonical_coverage_v366_patch")
        fn = getattr(v366, "canonical_symbol", None)
        if callable(fn):
            return str(fn(value) or "").strip().upper()
    except Exception:
        pass
    return str(value or "").strip().upper()


def _query_exact_fee(order_id: str, symbol: str, side: str) -> tuple[dict[str, Any] | None, str]:
    if order_id in _FEE_CACHE:
        fee, account = _FEE_CACHE[order_id]
        out: dict[str, Any] = {"fee": fee, "broker": "kraken", "fee_source": "authenticated_kraken_queryorders"}
        if account.startswith("user:"):
            out["account"] = account
        return out, "cache"
    try:
        v367 = importlib.import_module("bot.runtime_kraken_margin_protection_truth_v367_patch")
        brokers_fn = getattr(v367, "_account_brokers", None)
        private_call_fn = getattr(v367, "_private_call", None)
        if not callable(brokers_fn) or not callable(private_call_fn):
            return None, "kraken_authenticated_queryorders_unavailable"
        for account, broker in list(brokers_fn() or []):
            call = private_call_fn(broker)
            if not callable(call):
                continue
            try:
                payload = call("QueryOrders", {"txid": order_id, "trades": "true"})
            except Exception:
                continue
            if not isinstance(payload, Mapping) or payload.get("error"):
                continue
            rows = payload.get("result") or {}
            if not isinstance(rows, Mapping):
                continue
            row = rows.get(order_id)
            if not isinstance(row, Mapping):
                continue
            status = str(row.get("status") or "").strip().lower()
            if status not in _FINAL:
                continue
            vol_exec = _f(row.get("vol_exec"), 0.0)
            cost = _f(row.get("cost"), 0.0)
            if vol_exec <= 0.0 or cost <= 0.0 or "fee" not in row:
                continue
            fee = _f(row.get("fee"))
            if fee < 0.0:
                continue
            descr = row.get("descr") if isinstance(row.get("descr"), Mapping) else {}
            row_symbol = _canonical_symbol(descr.get("pair") or symbol)
            wanted_symbol = _canonical_symbol(symbol)
            row_side = str(descr.get("type") or side or "").strip().lower()
            wanted_side = str(side or "").strip().lower()
            if wanted_symbol and row_symbol and wanted_symbol != row_symbol:
                continue
            if wanted_side and row_side and wanted_side != row_side:
                continue
            account_s = str(account or "")
            _FEE_CACHE[order_id] = (float(fee), account_s)
            out = {"fee": float(fee), "broker": "kraken", "fee_source": "authenticated_kraken_queryorders"}
            if account_s.startswith("user:"):
                out["account"] = account_s
            return out, "authenticated_exact_match"
    except Exception as exc:
        return None, f"queryorders_exception:{type(exc).__name__}:{exc}"
    return None, "exact_order_fee_not_found"


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
                LOGGER.info(
                    "REALIZED_PNL_V413_NONCLOSE_IGNORED marker=%s order_id=%s symbol=%s role=entry opening_order_replay=true realized_pnl_unchanged=true",
                    MARKER, oid or "unknown", symbol,
                )
                return
            enriched = dict(result)
            if not _has_explicit_fee(enriched) and oid:
                fee_meta, reason = _query_exact_fee(oid, symbol, side)
                if fee_meta:
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
