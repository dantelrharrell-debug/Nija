"""Kraken broker-open margin position reconciliation v364.

Production evidence on 2026-09-04 proved that Kraken TradeBalance still showed
leveraged account state while the canonical Balance-owned position snapshot did
not include a broker-visible ETH margin long.  v354 correctly prevents a local
``pending_open`` intent from authorizing margin-exit semantics, but there was no
broker ``OpenPositions`` bridge to reconcile that pending intent once Kraken
itself reported the leveraged position as open.

v364 keeps spot Balance ownership unchanged.  It uses authenticated Kraken
``OpenPositions`` only as broker position-state truth for the dedicated margin
ledger immediately before Kraken SELL exit routing.  It never treats an order
ACK/status/order-id or OpenPositions presence as confirmed-fill execution proof,
never grants execution readiness, and never changes activation/kill-switch or
rejection history.  For broker-confirmed long margin exposure, base-quantity
exits are capped to the remaining broker-open units; ambiguous/mixed exposure or
an unverifiable known-margin exit fails closed.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import math
import os
from functools import wraps
from typing import Any, Dict, Mapping, Optional

LOGGER = logging.getLogger("nija.runtime_kraken_openpositions_margin_reconciliation_v364")
MARKER = "20260904-runtime-kraken-openpositions-margin-reconciliation-v364"
RELEASE_ID = "20260904-runtime-convergence-v364"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_OPENPOSITIONS_MARGIN_RECONCILIATION_V364_READY"
_PATCH_ATTR = "_nija_v364_kraken_openpositions_margin_reconciliation"
_EPS = 1e-12


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _canonical_symbol(value: Any) -> str:
    raw = str(value or "").strip()
    try:
        module = importlib.import_module("bot.runtime_kraken_terminal_symbol_canonicalization_v261_patch")
        canonical = getattr(module, "_canonical_terminal_symbol", None)
        if callable(canonical):
            raw = str(canonical(raw) or raw)
    except Exception:
        pass
    compact = raw.upper().replace("/", "-").replace("_", "-")
    if "-" not in compact:
        known = {
            "XETHZUSD": "ETH-USD", "XXBTZUSD": "BTC-USD", "XXRPZUSD": "XRP-USD",
            "XETCZUSD": "ETC-USD", "XLTCZUSD": "LTC-USD", "XXLMZUSD": "XLM-USD",
            "XMLNZUSD": "MLN-USD", "XDGUSD": "DOGE-USD",
        }
        compact = known.get(compact, compact)
    return compact


def _extract_long_margin_truth(response: Any, symbol: str) -> Dict[str, Any]:
    """Return aggregate broker-open long margin truth for one Kraken pair.

    Presence here is position-state evidence only.  It is deliberately not fill
    proof and must never be consumed by execution-readiness ownership.
    """
    if not isinstance(response, Mapping):
        return {"ok": False, "reason": "invalid_openpositions_payload"}
    errors = response.get("error") or []
    if isinstance(errors, str):
        errors = [errors]
    if errors:
        return {"ok": False, "reason": "openpositions_rejected", "errors": list(errors)}
    rows = response.get("result") or {}
    if not isinstance(rows, Mapping):
        return {"ok": False, "reason": "invalid_openpositions_result"}

    target = _canonical_symbol(symbol)
    long_rows = []
    opposite_rows = []
    for position_id, raw in rows.items():
        if not isinstance(raw, Mapping):
            continue
        if _canonical_symbol(raw.get("pair")) != target:
            continue
        vol = max(0.0, _float(raw.get("vol")))
        closed = max(0.0, _float(raw.get("vol_closed")))
        remaining = max(0.0, vol - closed)
        if remaining <= _EPS:
            continue
        side = str(raw.get("type") or "").strip().lower()
        item = (str(position_id), raw, remaining, vol)
        if side == "buy":
            long_rows.append(item)
        else:
            opposite_rows.append(item)

    if long_rows and opposite_rows:
        return {"ok": False, "reason": "mixed_direction_openpositions", "ambiguous": True}
    if not long_rows:
        return {"ok": True, "found": False, "symbol": target}

    total_units = 0.0
    total_notional = 0.0
    leverage_values = []
    ids = []
    for position_id, row, remaining, original_vol in long_rows:
        ids.append(position_id)
        total_units += remaining
        value = max(0.0, _float(row.get("value")))
        cost = max(0.0, _float(row.get("cost")))
        if value > 0:
            notional = value
        elif cost > 0 and original_vol > _EPS:
            notional = cost * min(1.0, remaining / original_vol)
        else:
            notional = 0.0
        total_notional += notional
        margin = max(0.0, _float(row.get("margin")))
        if margin > _EPS and cost > _EPS:
            inferred = int(round(cost / margin))
            if 2 <= inferred <= 3:
                leverage_values.append(inferred)

    if total_units <= _EPS or total_notional <= _EPS:
        return {
            "ok": False,
            "reason": "openpositions_missing_authoritative_units_or_notional",
            "symbol": target,
        }
    leverage = max(leverage_values) if leverage_values else None
    return {
        "ok": True,
        "found": True,
        "symbol": target,
        "remaining_units": total_units,
        "notional_usd": total_notional,
        "leverage": leverage,
        "position_ids": ids,
        "broker_position_state_only": True,
        "confirmed_fill_proof": False,
    }


def _ledger_record(account_id: str, symbol: str) -> Dict[str, Any]:
    try:
        ledger_module = importlib.import_module("bot.margin_position_ledger")
        ledger = ledger_module.get_margin_position_ledger()
        return ledger.get_record(
            broker="kraken", account_id=account_id, subaccount_id="",
            symbol=_canonical_symbol(symbol), asset_class="crypto",
        ) or {}
    except Exception:
        return {}


def _known_margin_intent(row: Mapping[str, Any]) -> bool:
    lifecycle = str(row.get("lifecycle_status") or "").strip().lower()
    leverage = int(max(1.0, _float(row.get("leverage"), 1.0)))
    return leverage > 1 and lifecycle in {"pending_open", "open", "reducing"}


def _reconcile_open_position(broker: Any, account_id: str, symbol: str) -> Dict[str, Any]:
    api_call = getattr(broker, "_kraken_api_call", None)
    if not callable(api_call):
        return {"ok": False, "reason": "kraken_private_api_unavailable"}
    try:
        response = api_call("OpenPositions", {"docalcs": "true"})
    except Exception as exc:
        return {"ok": False, "reason": f"openpositions_exception:{type(exc).__name__}"}
    truth = _extract_long_margin_truth(response, symbol)
    if not truth.get("ok") or not truth.get("found"):
        return truth

    try:
        ledger_module = importlib.import_module("bot.margin_position_ledger")
        ledger = ledger_module.get_margin_position_ledger()
        kwargs = dict(
            broker="kraken",
            account_id=account_id,
            subaccount_id="",
            symbol=str(truth["symbol"]),
            asset_class="crypto",
            broker_units=float(truth["remaining_units"]),
            broker_notional_usd=float(truth["notional_usd"]),
        )
        if truth.get("leverage") in {2, 3}:
            kwargs["leverage"] = int(truth["leverage"])
            kwargs["leverage_authoritative"] = True
        reconciled = ledger.reconcile_snapshot(**kwargs)
        record = (reconciled or {}).get("record") or {}
    except Exception as exc:
        return {"ok": False, "reason": f"margin_ledger_reconcile_failed:{type(exc).__name__}"}

    lifecycle = str(record.get("lifecycle_status") or "").strip().lower()
    leverage = int(max(1.0, _float(record.get("leverage"), 1.0)))
    if lifecycle not in {"open", "reducing"} or leverage <= 1:
        return {"ok": False, "reason": "margin_ledger_not_authoritative_after_reconcile"}

    LOGGER.critical(
        "KRAKEN_OPENPOSITIONS_MARGIN_V364_RECONCILED marker=%s account=%s symbol=%s "
        "lifecycle=%s leverage=%sx remaining_units=%.12f notional_usd=%.8f "
        "broker_position_state_only=true ack_not_fill=true execution_proof_fabricated=false "
        "execution_ready_unchanged=true spot_balance_ownership_unchanged=true",
        MARKER, account_id, truth["symbol"], lifecycle, leverage,
        float(truth["remaining_units"]), float(truth["notional_usd"]),
    )
    truth["record"] = record
    return truth


def _patch_submitter() -> bool:
    module = importlib.import_module("bot.pipeline_order_submitter")
    current = getattr(module, "submit_market_order_via_pipeline", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current
    signature = inspect.signature(original)

    @wraps(original)
    def submit_v364(*args: Any, **kwargs: Any):
        try:
            bound = signature.bind_partial(*args, **kwargs)
            broker = bound.arguments.get("broker")
            symbol = str(bound.arguments.get("symbol") or "").strip()
            side = str(bound.arguments.get("side") or "").strip().lower()
            preferred = module._resolve_preferred_broker(broker)
            if preferred != "kraken" or side != "sell":
                return original(*args, **kwargs)

            # Match the original writer fence before any authenticated private read.
            module.assert_distributed_writer_authority()
            account_id = str(
                bound.arguments.get("account_id_override")
                or module._resolve_account_id(broker, preferred)
            ).strip().lower()
            prior_row = _ledger_record(account_id, symbol)
            truth = _reconcile_open_position(broker, account_id, symbol)

            if not truth.get("ok"):
                if _known_margin_intent(prior_row):
                    LOGGER.error(
                        "KRAKEN_OPENPOSITIONS_MARGIN_V364_EXIT_BLOCKED marker=%s account=%s symbol=%s "
                        "reason=%s known_margin_intent=true fail_closed=true",
                        MARKER, account_id, symbol, truth.get("reason"),
                    )
                    return {
                        "status": "error",
                        "error": "Kraken margin exit blocked: authoritative OpenPositions unavailable",
                        "symbol": symbol,
                        "account_id": account_id,
                        "margin": True,
                    }
                return original(*args, **kwargs)

            if not truth.get("found"):
                return original(*args, **kwargs)

            size_type = str(bound.arguments.get("size_type") or "quote").strip().lower()
            requested = max(0.0, _float(bound.arguments.get("quantity")))
            authoritative = max(0.0, _float(truth.get("remaining_units")))
            if size_type != "base":
                return {
                    "status": "error",
                    "error": "Kraken margin exit requires authoritative base quantity",
                    "symbol": symbol,
                    "account_id": account_id,
                    "margin": True,
                }
            if requested <= _EPS or authoritative <= _EPS:
                return {
                    "status": "error", "error": "Kraken margin exit has no authoritative quantity",
                    "symbol": symbol, "account_id": account_id, "margin": True,
                }
            safe_quantity = min(requested, authoritative)
            if safe_quantity < requested:
                LOGGER.critical(
                    "KRAKEN_OPENPOSITIONS_MARGIN_V364_QUANTITY_CAPPED marker=%s account=%s symbol=%s "
                    "requested=%.12f authoritative_remaining=%.12f submitted=%.12f "
                    "oversell_prevented=true",
                    MARKER, account_id, symbol, requested, authoritative, safe_quantity,
                )
            bound.arguments["quantity"] = safe_quantity
            metadata = dict(bound.arguments.get("metadata_override") or {})
            metadata.update({
                "kraken_openpositions_margin_v364": True,
                "authoritative_margin_remaining_units": authoritative,
                "broker_position_state_only": True,
                "confirmed_fill_proof": False,
            })
            bound.arguments["metadata_override"] = metadata
            return original(*bound.args, **bound.kwargs)
        except Exception as exc:
            LOGGER.exception(
                "KRAKEN_OPENPOSITIONS_MARGIN_V364_GUARD_ERROR marker=%s error=%s:%s fail_closed_for_known_margin=true",
                MARKER, type(exc).__name__, exc,
            )
            try:
                bound = signature.bind_partial(*args, **kwargs)
                broker = bound.arguments.get("broker")
                symbol = str(bound.arguments.get("symbol") or "")
                preferred = module._resolve_preferred_broker(broker)
                account_id = str(
                    bound.arguments.get("account_id_override")
                    or module._resolve_account_id(broker, preferred)
                ).strip().lower()
                if preferred == "kraken" and str(bound.arguments.get("side") or "").lower() == "sell" and _known_margin_intent(_ledger_record(account_id, symbol)):
                    return {
                        "status": "error", "error": "Kraken margin exit authority guard failed closed",
                        "symbol": symbol, "account_id": account_id, "margin": True,
                    }
            except Exception:
                pass
            return original(*args, **kwargs)

    setattr(submit_v364, _PATCH_ATTR, True)
    setattr(submit_v364, "__wrapped__", original)
    module.submit_market_order_via_pipeline = submit_v364
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_openpositions_margin_reconciliation_v364"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    patched = manifest = False
    try:
        patched = _patch_submitter()
        manifest = _register_manifest()
    except Exception as exc:
        LOGGER.exception("RUNTIME_KRAKEN_OPENPOSITIONS_MARGIN_V364_INSTALL_ERROR marker=%s error=%s:%s", MARKER, type(exc).__name__, exc)
    ready = bool(patched and manifest)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    (LOGGER.critical if ready else LOGGER.error)(
        "RUNTIME_KRAKEN_OPENPOSITIONS_MARGIN_V364_%s marker=%s ready=%s "
        "openpositions_position_truth_only=true pending_open_not_fill_proof=true spot_balance_ownership_unchanged=true "
        "margin_exit_quantity_capped_to_broker_remaining=true mixed_direction_fail_closed=true "
        "execution_ready_unchanged=true forced_trade=false forced_activation=false kill_switch_unchanged=true "
        "rejection_history_unchanged=true writer_nonce_risk_capital_position_sync_ecel_broker_health_minimum_order_ack_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
    )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook", "_patch_submitter",
    "_extract_long_margin_truth", "_reconcile_open_position",
]
