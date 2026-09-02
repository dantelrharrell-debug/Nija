"""Coinbase nested ACK/fill truth and stale rejection recovery v345.

Production on 2026-09-02 proved Coinbase was returning successful Advanced Trade
responses with real nested ``order.success_response.order_id`` values, while the
v328 canonical fill verifier looked only at top-level order-id fields.  The
result was paradoxical telemetry: successful Coinbase BUY/SELL submissions were
recorded as ``Exchange response lacks real order id`` and poisoned the exchange
rejection-rate kill switch.

v345 is deliberately monotonic:
* recognizes Coinbase nested order IDs as ACK proof only;
* when fill-specific price/notional is absent, performs a read-only Coinbase
  ``get_order`` reconciliation and accepts a fill only when that response proves
  a final filled state plus positive fill price and quantity/notional;
* never promotes requested notional, current market price, price hints, or an ACK
  alone into fill proof;
* classifies local dust/INVALID_SIZE outcomes and ACK-with-real-order-id pending
  reconciliation as non-exchange-health failures so they cannot poison the
  exchange rejection-rate detector;
* extends v344's one-time 5/5 polluted-latch recovery only to the exact historical
  false-reject shapes now observed in production. Unknown/mixed/auth/risk/outage
  failures remain fail-closed and preserve the kill switch.
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

LOGGER = logging.getLogger("nija.runtime_coinbase_fill_truth_v345")
MARKER = "20260902-runtime-coinbase-fill-truth-v345"
RELEASE_ID = "20260902-runtime-convergence-v345"
_READY_FLAG = "NIJA_RUNTIME_COINBASE_FILL_TRUTH_V345_READY"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_ORDER_ID_PATCH = "_nija_coinbase_nested_order_id_v345"
_SUBMIT_PATCH = "_nija_coinbase_fill_reconcile_v345"
_CLASSIFIER_PATCH = "_nija_coinbase_reject_truth_v345"
_V344_PATCH = "_nija_v344_recovery_truth_v345"


def _f(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return parsed if math.isfinite(parsed) and parsed > 0.0 else 0.0


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        try:
            out = value.to_dict()
            if isinstance(out, Mapping):
                return dict(out)
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return {k: v for k, v in vars(value).items() if not str(k).startswith("_")}
        except Exception:
            pass
    return {}


def _nested(container: Any, *keys: str) -> Any:
    cur = container
    for key in keys:
        if isinstance(cur, Mapping):
            cur = cur.get(key)
        else:
            cur = getattr(cur, key, None)
        if cur is None:
            return None
    return cur


def _extract_order_id(result: Any) -> str:
    candidates = (
        _nested(result, "order_id"),
        _nested(result, "id"),
        _nested(result, "exchange_order_id"),
        _nested(result, "txid"),
        _nested(result, "success_response", "order_id"),
        _nested(result, "order", "order_id"),
        _nested(result, "order", "success_response", "order_id"),
        _nested(result, "raw", "order_id"),
        _nested(result, "raw", "success_response", "order_id"),
    )
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def _extract_status(result: Any) -> str:
    for candidate in (
        _nested(result, "status"),
        _nested(result, "state"),
        _nested(result, "order", "status"),
        _nested(result, "raw", "status"),
    ):
        text = str(candidate or "").strip().lower().replace(" ", "_")
        if text:
            return text
    return ""


def _extract_fill_price(result: Any) -> float:
    paths = (
        ("filled_price",), ("average_filled_price",), ("average_fill_price",),
        ("avg_price",), ("executed_price",), ("execution_price",),
        ("order", "average_filled_price"), ("order", "filled_price"),
        ("raw", "average_filled_price"), ("raw", "filled_price"),
    )
    for path in paths:
        value = _f(_nested(result, *path))
        if value > 0.0:
            return value
    return 0.0


def _extract_filled_qty(result: Any) -> float:
    paths = (
        ("filled_size",), ("filled_volume",), ("filled_quantity",),
        ("executed_qty",), ("executed_quantity",),
        ("order", "filled_size"), ("order", "filled_quantity"),
        ("raw", "filled_size"), ("raw", "filled_quantity"),
    )
    for path in paths:
        value = _f(_nested(result, *path))
        if value > 0.0:
            return value
    return 0.0


def _extract_filled_usd(result: Any, price: float) -> float:
    paths = (
        ("filled_size_usd",), ("filled_value",), ("filled_notional",),
        ("executed_value",), ("executed_notional",), ("filled_quote",),
        ("order", "filled_value"), ("order", "total_value_after_fees"),
        ("raw", "filled_value"), ("raw", "total_value_after_fees"),
    )
    for path in paths:
        value = _f(_nested(result, *path))
        if value > 0.0:
            return value
    qty = _extract_filled_qty(result)
    return qty * price if qty > 0.0 and price > 0.0 else 0.0


def _is_coinbase(broker: Any) -> bool:
    btype = getattr(broker, "broker_type", None)
    label = str(getattr(btype, "value", btype) or "").lower()
    cls = type(broker).__name__.lower()
    return "coinbase" in label or "coinbase" in cls


def _coinbase_read_order(broker: Any, order_id: str) -> dict[str, Any]:
    """Read one Coinbase order without mutating execution state."""
    get_status = getattr(broker, "get_order_status", None)
    if callable(get_status):
        try:
            value = get_status(order_id)
            mapped = _mapping(value)
            if mapped:
                return mapped
        except TypeError:
            try:
                value = get_status(order_id=order_id)
                mapped = _mapping(value)
                if mapped:
                    return mapped
            except Exception:
                pass
        except Exception:
            pass

    client = getattr(broker, "client", None)
    get_order = getattr(client, "get_order", None)
    if callable(get_order):
        for kwargs in ({"order_id": order_id}, {"id": order_id}):
            try:
                value = get_order(**kwargs)
                mapped = _mapping(value)
                if mapped:
                    return mapped
            except TypeError:
                continue
            except Exception:
                break
    return {}


def _enrich_coinbase_ack_with_fill(broker: Any, result: Any) -> Any:
    if not _is_coinbase(broker) or not isinstance(result, Mapping):
        return result
    enriched = dict(result)
    order_id = _extract_order_id(enriched)
    if order_id:
        enriched.setdefault("order_id", order_id)

    # If the submit response already contains genuine fill-specific evidence,
    # keep it. Otherwise perform bounded read-only reconciliation.
    price = _extract_fill_price(enriched)
    filled_usd = _extract_filled_usd(enriched, price)
    status = _extract_status(enriched)
    if order_id and (price <= 0.0 or filled_usd <= 0.0 or status not in {"filled", "closed", "complete", "completed", "executed"}):
        observed = _coinbase_read_order(broker, order_id)
        if observed:
            observed_order = _mapping(observed.get("order")) if isinstance(observed, Mapping) else {}
            source = observed_order or observed
            observed_status = _extract_status(source)
            observed_price = _extract_fill_price(source)
            observed_qty = _extract_filled_qty(source)
            observed_usd = _extract_filled_usd(source, observed_price)
            if observed_status:
                enriched["status"] = observed_status
            if observed_price > 0.0:
                enriched["filled_price"] = observed_price
            if observed_qty > 0.0:
                enriched["filled_size"] = observed_qty
            if observed_usd > 0.0:
                enriched["filled_size_usd"] = observed_usd
            enriched["coinbase_order_reconciled"] = True
            LOGGER.critical(
                "COINBASE_FILL_V345_RECONCILED marker=%s order_id=%s status=%s fill_price=%.10f filled_qty=%.12f filled_usd=%.8f "
                "read_only=true requested_notional_promoted=false market_price_promoted=false fill_fabricated=false",
                MARKER, order_id, observed_status or "unknown", observed_price, observed_qty, observed_usd,
            )
    return enriched


def _patch_v328() -> bool:
    module = importlib.import_module("bot.runtime_confirmed_fill_profitability_v328_patch")

    current_order_id = getattr(module, "_order_id", None)
    if not callable(current_order_id):
        return False
    if not getattr(current_order_id, _ORDER_ID_PATCH, False):
        @wraps(current_order_id)
        def order_id_v345(result: Mapping[str, Any]) -> str:
            return _extract_order_id(result) or str(current_order_id(result) or "").strip()
        setattr(order_id_v345, _ORDER_ID_PATCH, True)
        setattr(order_id_v345, "__wrapped__", current_order_id)
        module._order_id = order_id_v345

    current_submit = getattr(module, "_submit_direct", None)
    if not callable(current_submit):
        return False
    if not getattr(current_submit, _SUBMIT_PATCH, False):
        @wraps(current_submit)
        def submit_v345(broker: Any, symbol: str, side: str, size_usd: float, metadata: Mapping[str, Any]):
            result = current_submit(broker, symbol, side, size_usd, metadata)
            return _enrich_coinbase_ack_with_fill(broker, result)
        setattr(submit_v345, _SUBMIT_PATCH, True)
        setattr(submit_v345, "__wrapped__", current_submit)
        module._submit_direct = submit_v345

    return bool(getattr(module._order_id, _ORDER_ID_PATCH, False) and getattr(module._submit_direct, _SUBMIT_PATCH, False))


def _known_non_exchange_health(reason: Any) -> bool:
    text = str(reason or "").strip().lower()
    if not text:
        return False
    dust = (
        "skipped_dust" in text and "invalid_size" in text
    ) or "position too small (dust)" in text or "permanent_dust_unsellable" in text
    ack_pending = (
        "ack timeout pending reconciliation order_id=" in text
        or "fill_specific_price_or_notional_missing" in text
    )
    historical_nested_ack = (
        "exchange response lacks real order id; fill not proven" in text
        and ("'success': true" in text or '"success": true' in text)
        and ("'order_id':" in text or '"order_id":' in text)
    )
    return bool(dust or ack_pending or historical_nested_ack)


def _patch_rejection_classifier() -> bool:
    module = importlib.import_module("bot.exchange_reject_dispatch_provenance_v228_patch")
    current = getattr(module, "_is_non_exchange_rejection", None)
    if not callable(current):
        return False
    if getattr(current, _CLASSIFIER_PATCH, False):
        return True

    @wraps(current)
    def classifier_v345(reason: Any) -> bool:
        return _known_non_exchange_health(reason) or bool(current(reason))

    setattr(classifier_v345, _CLASSIFIER_PATCH, True)
    setattr(classifier_v345, "__wrapped__", current)
    module._is_non_exchange_rejection = classifier_v345
    return True


def _patch_v344_recovery_truth() -> bool:
    module = importlib.import_module("bot.runtime_coinbase_exit_recovery_v344_patch")
    current = getattr(module, "_deterministic_non_health", None)
    if not callable(current):
        return False
    if getattr(current, _V344_PATCH, False):
        return True

    @wraps(current)
    def deterministic_v345(reason: Any) -> bool:
        return _known_non_exchange_health(reason) or bool(current(reason))

    setattr(deterministic_v345, _V344_PATCH, True)
    setattr(deterministic_v345, "__wrapped__", current)
    module._deterministic_non_health = deterministic_v345
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_coinbase_fill_truth_v345"] = _READY_FLAG
        return True
    except Exception:
        return False


def _worker() -> None:
    while True:
        try:
            _patch_v328()
            _patch_rejection_classifier()
            _patch_v344_recovery_truth()
            # v344 owns the guarded recovery transaction; v345 only expands its
            # deterministic classifier to the exact newly-proven false shapes.
            v344 = importlib.import_module("bot.runtime_coinbase_exit_recovery_v344_patch")
            attempt = getattr(v344, "attempt_polluted_latch_recovery_once", None)
            if callable(attempt):
                attempt()
        except Exception:
            LOGGER.debug("V345 worker pulse failed", exc_info=True)
        time.sleep(2.0)


def install_import_hook() -> bool:
    global _THREAD
    with _LOCK:
        fill_ready = reject_ready = recovery_ready = manifest_ready = False
        try:
            fill_ready = _patch_v328()
            reject_ready = _patch_rejection_classifier()
            recovery_ready = _patch_v344_recovery_truth()
            manifest_ready = _register_manifest()
        except Exception as exc:
            LOGGER.exception("RUNTIME_COINBASE_FILL_TRUTH_V345_INSTALL_ERROR marker=%s err=%s:%s", MARKER, type(exc).__name__, exc)
        ready = bool(fill_ready and reject_ready and recovery_ready and manifest_ready)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready and (_THREAD is None or not _THREAD.is_alive()):
            _THREAD = threading.Thread(target=_worker, name="CoinbaseFillTruthV345", daemon=True)
            _THREAD.start()
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_COINBASE_FILL_TRUTH_V345_%s marker=%s ready=%s nested_order_id=%s read_only_fill_reconciliation=%s "
            "dust_reject_provenance=%s guarded_v344_recovery=%s requested_notional_promoted=false market_price_promoted=false "
            "ack_alone_not_fill=true rejection_thresholds_unchanged=true generic_killswitch_autoclear=false "
            "writer_nonce_capital_risk_position_sync_ecel_broker_health_gates_unchanged=true safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(), str(fill_ready).lower(),
            str(fill_ready).lower(), str(reject_ready).lower(), str(recovery_ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook", "_extract_order_id",
    "_enrich_coinbase_ack_with_fill", "_known_non_exchange_health",
]
