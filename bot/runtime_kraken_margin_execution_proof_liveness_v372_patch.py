"""Kraken margin execution-proof recovery liveness v372.

The v367 policy is intentionally strict: an authenticated OpenPositions row is
position-state evidence only, while execution readiness requires an exact opening
order id to be re-proven through authenticated QueryOrders and then admitted by
the existing v328/v346 canonical confirmed-fill chain.

Production after a clean Render redeploy exposed a liveness gap.  v366 was
successfully reading the live Kraken margin position, but it discarded each
OpenPositions row's ``ordertxid`` while aggregating position state.  v367 then
issued a second independent OpenPositions read to rediscover that id.  Under
startup/private-API contention that duplicate read could fail silently, leaving
``execution_ready`` pending even though v366 already held authenticated position
state from the same endpoint.

v372 closes only that liveness gap:

* enrich v366's authenticated OpenPositions normalization with the opening order
  id, position id and broker opening timestamp while keeping it explicitly
  position-state-only;
* reuse v366's short-lived authenticated cache instead of requiring a duplicate
  OpenPositions read;
* exact-query every candidate through QueryOrders and require a final status,
  positive ``vol_exec`` and positive ``cost``;
* hand only that exact authenticated fill row to v328, which remains the sole
  canonical fill verifier and v346 marker owner;
* keep all writer, nonce, risk, capital, position, kill-switch, ECEL, broker
  health, minimum-order, ACK/fill and activation gates unchanged.

No OpenPositions row, ACK, remembered notional, requested size, current/market
price, connectivity state or stale marker is promoted to execution proof.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
import time
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_margin_execution_proof_liveness_v372")
MARKER = "20260905-runtime-kraken-margin-execution-proof-liveness-v372"
RELEASE_ID = "20260905-runtime-convergence-v372"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_MARGIN_EXECUTION_PROOF_LIVENESS_V372_READY"
_PATCH_ATTR = "_nija_v372_margin_execution_proof_liveness"
_LOCK = threading.RLock()
_EPS = 1e-12
_CACHE_RESET_DONE = False
_LAST_DIAGNOSTIC: dict[str, float] = {}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _v366():
    return importlib.import_module("bot.runtime_kraken_margin_canonical_coverage_v366_patch")


def _v367():
    return importlib.import_module("bot.runtime_kraken_margin_protection_truth_v367_patch")


def _log_due(key: str, interval_s: float = 30.0) -> bool:
    now = time.monotonic()
    previous = float(_LAST_DIAGNOSTIC.get(key, 0.0) or 0.0)
    if now - previous < interval_s:
        return False
    _LAST_DIAGNOSTIC[key] = now
    return True


def _max_age_s() -> float:
    try:
        value = float(
            os.environ.get("NIJA_KRAKEN_MARGIN_EXECUTION_PROOF_MAX_AGE_S", "")
            or 7 * 24 * 3600.0
        )
    except (TypeError, ValueError):
        value = 7 * 24 * 3600.0
    return max(300.0, value)


def _patch_v366_openposition_metadata() -> bool:
    """Preserve exact opening-order metadata from v366's authenticated read.

    This enriches position-state rows only.  ``confirmed_fill_proof`` remains
    false and no execution marker is written here.
    """
    module = _v366()
    current = getattr(module, "normalise_open_positions", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def normalise_v372(payload: Any):
        truth = current(payload)
        if not isinstance(truth, Mapping) or not bool(truth.get("ok")):
            return truth
        positions = truth.get("positions")
        if not isinstance(positions, dict):
            return truth
        if not isinstance(payload, Mapping):
            return truth
        result = payload.get("result") or {}
        if not isinstance(result, Mapping):
            return truth

        for position_id, raw in result.items():
            if not isinstance(raw, Mapping):
                continue
            side = str(raw.get("type") or "").strip().lower()
            if side != "buy":
                continue
            volume = max(0.0, _f(raw.get("vol")))
            closed = max(0.0, _f(raw.get("vol_closed")))
            if volume <= _EPS or volume - closed <= _EPS:
                continue
            symbol = module.canonical_symbol(raw.get("pair"))
            row = positions.get(symbol)
            if not symbol or not isinstance(row, dict):
                continue
            order_id = str(raw.get("ordertxid") or "").strip()
            if not order_id:
                continue
            candidate = {
                "order_id": order_id,
                "position_id": str(position_id or "").strip(),
                "opened_at_epoch": max(0.0, _f(raw.get("opentm"))),
                "symbol": symbol,
                "side": side,
            }
            existing = [dict(item) for item in row.get("opening_orders", ()) if isinstance(item, Mapping)]
            identity = (candidate["order_id"], candidate["position_id"])
            if identity not in {
                (str(item.get("order_id") or ""), str(item.get("position_id") or ""))
                for item in existing
            }:
                existing.append(candidate)
            existing.sort(key=lambda item: (str(item.get("order_id") or ""), str(item.get("position_id") or "")))
            row["opening_orders"] = tuple(existing)
            row["opening_order_ids"] = tuple(
                sorted({str(item.get("order_id") or "") for item in existing if str(item.get("order_id") or "")})
            )
            # Preserve the explicit v366 boundary: this metadata is not fill proof.
            row["broker_position_state_only"] = True
            row["confirmed_fill_proof"] = False
        return truth

    setattr(normalise_v372, _PATCH_ATTR, True)
    setattr(normalise_v372, "__wrapped__", current)
    module.normalise_open_positions = normalise_v372
    return True


def _reset_v366_cache_once() -> None:
    global _CACHE_RESET_DONE
    if _CACHE_RESET_DONE:
        return
    module = _v366()
    lock = getattr(module, "_LOCK", None)
    cache = getattr(module, "_CACHE", None)
    try:
        if lock is not None:
            with lock:
                if isinstance(cache, dict):
                    cache.clear()
        elif isinstance(cache, dict):
            cache.clear()
        _CACHE_RESET_DONE = True
        LOGGER.info(
            "KRAKEN_MARGIN_EXECUTION_PROOF_V372_CACHE_REFRESH marker=%s "
            "v366_openpositions_cache_cleared=true broker_state_mutated=false "
            "execution_proof_fabricated=false safety_gates_bypassed=false",
            MARKER,
        )
    except Exception:
        LOGGER.debug("v372 v366 cache refresh deferred", exc_info=True)


def _candidate_opening_orders(account: str, broker: Any) -> tuple[list[dict[str, Any]], str]:
    module = _v366()
    fetch = getattr(module, "fetch_margin_positions", None)
    if not callable(fetch):
        return [], "v366_fetch_unavailable"
    try:
        ok, positions, reason = fetch(broker, account=account, force=False)
    except Exception as exc:
        return [], f"v366_fetch_exception:{type(exc).__name__}"
    if not ok:
        return [], f"v366_fetch_unproven:{reason}"

    now = time.time()
    max_age = _max_age_s()
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for symbol, position in dict(positions or {}).items():
        if not isinstance(position, Mapping):
            continue
        for raw in tuple(position.get("opening_orders", ()) or ()):
            if not isinstance(raw, Mapping):
                continue
            order_id = str(raw.get("order_id") or "").strip()
            position_id = str(raw.get("position_id") or "").strip()
            opened = max(0.0, _f(raw.get("opened_at_epoch")))
            if not order_id:
                continue
            if opened > 0.0 and now - opened > max_age:
                continue
            identity = (order_id, position_id)
            if identity in seen:
                continue
            seen.add(identity)
            candidates.append(
                {
                    "order_id": order_id,
                    "position_id": position_id,
                    "opened_at_epoch": opened,
                    "symbol": module.canonical_symbol(raw.get("symbol") or symbol),
                    "side": str(raw.get("side") or "buy").strip().lower(),
                }
            )
    candidates.sort(key=lambda item: float(item.get("opened_at_epoch") or 0.0), reverse=True)
    return candidates, str(reason or "ok")


def _exact_queryorders_fill(call: Any, opening: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    order_id = str(opening.get("order_id") or "").strip()
    if not order_id:
        return None, "order_id_missing"
    try:
        payload = call("QueryOrders", {"txid": order_id, "trades": "true"})
    except Exception as exc:
        return None, f"queryorders_exception:{type(exc).__name__}"
    if not isinstance(payload, Mapping):
        return None, "queryorders_payload_invalid"
    errors = payload.get("error") or []
    if isinstance(errors, str):
        errors = [errors]
    if errors:
        return None, "queryorders_rejected:" + ",".join(str(item) for item in errors)
    result = payload.get("result") or {}
    if not isinstance(result, Mapping):
        return None, "queryorders_result_invalid"
    row = result.get(order_id)
    if not isinstance(row, Mapping):
        return None, "queryorders_exact_row_missing"
    status = str(row.get("status") or "").strip().lower()
    if status not in {"closed", "filled", "complete", "completed", "executed"}:
        return None, f"queryorders_nonfinal:{status or 'missing'}"
    vol_exec = max(0.0, _f(row.get("vol_exec")))
    cost = max(0.0, _f(row.get("cost")))
    if vol_exec <= _EPS:
        return None, "queryorders_fill_quantity_missing"
    if cost <= _EPS:
        return None, "queryorders_fill_cost_missing"
    price = max(0.0, _f(row.get("price")))
    if price <= _EPS:
        price = cost / vol_exec
    if price <= _EPS:
        return None, "queryorders_fill_price_unproven"
    descr = row.get("descr") if isinstance(row.get("descr"), Mapping) else {}
    symbol = _v366().canonical_symbol(descr.get("pair") or opening.get("symbol"))
    side = str(descr.get("type") or opening.get("side") or "buy").strip().lower()
    if not symbol or side not in {"buy", "sell"}:
        return None, "queryorders_symbol_side_unproven"
    return {
        "order_id": order_id,
        "status": "closed",
        "filled_price": price,
        "filled_quantity": vol_exec,
        "authenticated_kraken_queryorders": True,
        "opening_position_id": opening.get("position_id"),
        "symbol": symbol,
        "side": side,
    }, "ok"


def recover_execution_proof_once() -> int:
    """Recover only from exact authenticated QueryOrders evidence."""
    v367 = _v367()
    marker_probe = getattr(v367, "_execution_marker_ready", None)
    if callable(marker_probe):
        try:
            ready, _detail = marker_probe()
            if ready:
                return 0
        except Exception:
            pass

    brokers_fn = getattr(v367, "_account_brokers", None)
    brokers = list(brokers_fn() or []) if callable(brokers_fn) else []
    if not brokers:
        if _log_due("no_brokers"):
            LOGGER.info(
                "KRAKEN_MARGIN_EXECUTION_PROOF_V372_DEFERRED marker=%s reason=no_kraken_account_brokers "
                "trading_fail_closed=true execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER,
            )
        return 0

    v328 = importlib.import_module("bot.runtime_confirmed_fill_profitability_v328_patch")
    normalize = getattr(v328, "_normalize_dict_fill", None)
    if not callable(normalize):
        if _log_due("v328_missing"):
            LOGGER.error(
                "KRAKEN_MARGIN_EXECUTION_PROOF_V372_DEFERRED marker=%s reason=v328_verifier_unavailable "
                "trading_fail_closed=true",
                MARKER,
            )
        return 0

    private_call_fn = getattr(v367, "_private_call", None)
    for account, broker in brokers:
        account_s = str(account or "")
        candidates, candidate_reason = _candidate_opening_orders(account_s, broker)
        if not candidates:
            if _log_due(f"no_candidates:{account_s}"):
                LOGGER.info(
                    "KRAKEN_MARGIN_EXECUTION_PROOF_V372_DEFERRED marker=%s account=%s "
                    "reason=no_authenticated_opening_order_candidates detail=%s "
                    "openpositions_not_fill=true trading_fail_closed=true execution_proof_fabricated=false "
                    "safety_gates_bypassed=false",
                    MARKER, account_s or "unknown", candidate_reason,
                )
            continue

        call = private_call_fn(broker) if callable(private_call_fn) else None
        if not callable(call):
            if _log_due(f"private_api:{account_s}"):
                LOGGER.info(
                    "KRAKEN_MARGIN_EXECUTION_PROOF_V372_DEFERRED marker=%s account=%s "
                    "reason=kraken_private_api_unavailable trading_fail_closed=true",
                    MARKER, account_s or "unknown",
                )
            continue

        LOGGER.info(
            "KRAKEN_MARGIN_EXECUTION_PROOF_V372_CANDIDATES marker=%s account=%s candidates=%d "
            "source=v366_authenticated_openpositions_cache exact_queryorders_required=true "
            "openpositions_not_fill=true execution_proof_fabricated=false",
            MARKER, account_s or "unknown", len(candidates),
        )
        for opening in candidates:
            proof, reason = _exact_queryorders_fill(call, opening)
            order_id = str(opening.get("order_id") or "")
            if proof is None:
                if _log_due(f"query:{account_s}:{order_id}"):
                    LOGGER.info(
                        "KRAKEN_MARGIN_EXECUTION_PROOF_V372_DEFERRED marker=%s account=%s order_id=%s "
                        "reason=%s exact_queryorders_match_required=true trading_fail_closed=true "
                        "execution_proof_fabricated=false safety_gates_bypassed=false",
                        MARKER, account_s or "unknown", order_id or "unknown", reason,
                    )
                continue
            try:
                normalize(proof, symbol=proof["symbol"], side=proof["side"])
            except Exception as exc:
                LOGGER.info(
                    "KRAKEN_MARGIN_EXECUTION_PROOF_V372_DEFERRED marker=%s account=%s order_id=%s "
                    "reason=canonical_v328_rejected:%s:%s trading_fail_closed=true "
                    "execution_proof_fabricated=false safety_gates_bypassed=false",
                    MARKER, account_s or "unknown", order_id, type(exc).__name__, exc,
                )
                continue

            LOGGER.critical(
                "KRAKEN_MARGIN_EXECUTION_PROOF_V372_RECOVERED marker=%s account=%s order_id=%s "
                "symbol=%s side=%s fill_price=%.10f filled_quantity=%.12f "
                "source=v366_authenticated_openpositions_cache exact_queryorders_match=true "
                "final_status_required=true positive_fill_quantity_required=true positive_fill_cost_required=true "
                "ack_not_fill=true openpositions_not_fill=true market_price_promoted=false "
                "requested_notional_promoted=false execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER, account_s or "unknown", order_id, proof["symbol"], proof["side"],
                float(proof["filled_price"]), float(proof["filled_quantity"]),
            )
            try:
                v346 = importlib.import_module("bot.runtime_execution_position_readiness_v346_patch")
                wake = getattr(v346, "_wake_activation_after_proof", None)
                if callable(wake):
                    wake()
                sync = getattr(v346, "_wake_position_sync", None)
                if callable(sync):
                    sync()
            except Exception:
                LOGGER.debug("v372 activation wake deferred", exc_info=True)
            return 1
    return 0


def _patch_v367_recovery() -> bool:
    module = _v367()
    current = getattr(module, "recover_execution_proof_once", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def recovery_v372():
        return recover_execution_proof_once()

    setattr(recovery_v372, _PATCH_ATTR, True)
    setattr(recovery_v372, "__wrapped__", current)
    module.recover_execution_proof_once = recovery_v372
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_margin_execution_proof_liveness_v372"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        try:
            if os.environ.get("NIJA_RUNTIME_KRAKEN_MARGIN_PROTECTION_TRUTH_V367_READY") != "1":
                raise RuntimeError("v367_not_ready")
            metadata = _patch_v366_openposition_metadata()
            recovery = _patch_v367_recovery()
            manifest = _register_manifest()
            ready = bool(metadata and recovery and manifest)
            if ready:
                _reset_v366_cache_once()
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "RUNTIME_KRAKEN_MARGIN_EXECUTION_PROOF_LIVENESS_V372_INSTALL_FAILED marker=%s "
                "error=%s:%s trading_fail_closed=true execution_proof_fabricated=false "
                "safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )

        os.environ[_READY_FLAG] = "1" if ready else "0"
        (LOGGER.critical if ready else LOGGER.error)(
            "RUNTIME_KRAKEN_MARGIN_EXECUTION_PROOF_LIVENESS_V372_%s marker=%s ready=%s "
            "authenticated_openpositions_metadata_preserved=true duplicate_openpositions_dependency_removed=true "
            "exact_queryorders_match_required=true final_status_required=true positive_fill_quantity_required=true "
            "positive_fill_cost_required=true canonical_v328_verifier_required=true canonical_v346_marker_owner=true "
            "ack_not_fill=true openpositions_not_fill=true current_price_not_fill=true requested_notional_not_fill=true "
            "writer_nonce_risk_capital_position_killswitch_ecel_broker_health_minimum_order_ack_fill_gates_unchanged=true "
            "forced_trade=false forced_activation=false execution_proof_fabricated=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        if ready:
            try:
                recover_execution_proof_once()
            except Exception:
                LOGGER.debug("v372 immediate recovery deferred", exc_info=True)
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "recover_execution_proof_once",
]
