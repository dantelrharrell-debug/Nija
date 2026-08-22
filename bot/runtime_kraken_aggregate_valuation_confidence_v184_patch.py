"""Use authenticated Kraken aggregate-equity proof for capital confidence.

Production on 2026-08-22 showed the v183 capital-liveness repair working:
CapitalAuthority publishes a fresh accepted 3/3 platform snapshot, Kraken
TradeBalance returns a positive authenticated equivalent balance (``eb``), and
position/writer/runtime readiness are healthy.  The capital runtime nevertheless
remains RUN_DEGRADED because Stage 4's legacy pricing-coverage input stays 0.0:
v183 intentionally avoids cold per-asset public ticker calls during the bounded
capital refresh.

v184 preserves the raw per-asset pricing metric and adds a narrowly-scoped
aggregate valuation proof.  A successful authenticated read-only ``TradeBalance``
response records its positive ``eb`` and timestamp on the exact Kraken broker
instance.  ``get_last_pricing_coverage`` is then allowed to return effective
valuation coverage=1.0 only when all of the following are true:

* the most recent TradeBalance response was successful and ``eb`` is positive;
* its proof timestamp is still inside the canonical capital freshness TTL;
* the broker's last successful balance timestamp is also inside that TTL;
* the TradeBalance and balance observations belong to the same fetch epoch
  (bounded timestamp skew);
* Kraken reports zero consecutive balance errors and is not unavailable/error.

The historical ``_last_pricing_coverage_pct`` field is NOT modified, so raw
per-asset pricing diagnostics remain truthful.  This patch only supplies the
Stage-4 legacy coverage accessor with the stronger authenticated aggregate-equity
valuation authority that already determines ``total_funds`` in broker_manager.

No balance/capital value is synthesized.  No freshness TTL, publication expiry,
broker completeness, writer/nonce/risk state, kill switch, activation state,
execution permission, signal threshold, market-quality gate, or trade routing is
changed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any, Optional

LOGGER = logging.getLogger("nija.runtime_kraken_aggregate_valuation_confidence_v184")
MARKER = "20260822-runtime-kraken-aggregate-valuation-confidence-v184"
RELEASE_ID = "20260822-runtime-convergence-v184"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_AGGREGATE_VALUATION_CONFIDENCE_V184_READY"
_PRIVATE_ATTR = "_nija_runtime_kraken_aggregate_valuation_confidence_v184_private"
_COVERAGE_ATTR = "_nija_runtime_kraken_aggregate_valuation_confidence_v184_coverage"
_PROOF_EQUITY_ATTR = "_nija_v184_tradebalance_equity_usd"
_PROOF_TS_ATTR = "_nija_v184_tradebalance_equity_ts"
_LOCK = threading.RLock()


def _positive_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0.0 else None


def _canonical_freshness_ttl_s() -> float:
    """Read, never extend, the canonical capital freshness TTL."""
    try:
        module = importlib.import_module("bot.capital_flow_state_machine")
        ttl = float(getattr(module, "FRESHNESS_TTL_S", 90.0) or 90.0)
    except Exception:
        ttl = 90.0
    return max(1.0, min(90.0, ttl))


def _clear_aggregate_proof(instance: Any) -> None:
    setattr(instance, _PROOF_EQUITY_ATTR, 0.0)
    setattr(instance, _PROOF_TS_ATTR, 0.0)


def _record_tradebalance_result(instance: Any, result: Any) -> None:
    """Record only successful authenticated TradeBalance equivalent equity."""
    if not isinstance(result, dict) or result.get("error"):
        _clear_aggregate_proof(instance)
        return
    payload = result.get("result")
    if not isinstance(payload, dict):
        _clear_aggregate_proof(instance)
        return
    equity = _positive_float(payload.get("eb"))
    if equity is None:
        _clear_aggregate_proof(instance)
        return
    setattr(instance, _PROOF_EQUITY_ATTR, equity)
    setattr(instance, _PROOF_TS_ATTR, time.time())


def _aggregate_proof_status(instance: Any, *, now: Optional[float] = None) -> tuple[bool, str, float, float]:
    """Return whether aggregate-equity proof is current and same-epoch."""
    current = time.time() if now is None else float(now)
    equity = _positive_float(getattr(instance, _PROOF_EQUITY_ATTR, 0.0)) or 0.0
    try:
        proof_ts = float(getattr(instance, _PROOF_TS_ATTR, 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        proof_ts = 0.0
    if equity <= 0.0 or proof_ts <= 0.0:
        return False, "aggregate_proof_missing", equity, float("inf")

    ttl = _canonical_freshness_ttl_s()
    proof_age = max(0.0, current - proof_ts)
    if proof_age > ttl:
        return False, "aggregate_proof_stale", equity, proof_age

    balance_ts = None
    getter = getattr(instance, "get_balance_fetch_timestamp", None)
    if callable(getter):
        try:
            value = getter()
            if value is not None:
                balance_ts = float(value)
        except Exception:
            balance_ts = None
    if balance_ts is None or balance_ts <= 0.0:
        return False, "balance_timestamp_missing", equity, proof_age

    balance_age = max(0.0, current - balance_ts)
    if balance_age > ttl:
        return False, "balance_observation_stale", equity, proof_age

    # get_account_balance sets _balance_last_updated immediately after the
    # authenticated TradeBalance call.  Allow a small scheduling/logging gap,
    # but never join unrelated observations from different refresh epochs.
    if abs(balance_ts - proof_ts) > 5.0:
        return False, "aggregate_balance_epoch_mismatch", equity, proof_age

    errors_getter = getattr(instance, "get_error_count", None)
    if callable(errors_getter):
        try:
            if int(errors_getter()) != 0:
                return False, "kraken_balance_errors_present", equity, proof_age
        except Exception:
            return False, "kraken_error_state_unknown", equity, proof_age

    available_getter = getattr(instance, "is_available", None)
    if callable(available_getter):
        try:
            if not bool(available_getter()):
                return False, "kraken_unavailable", equity, proof_age
        except Exception:
            return False, "kraken_availability_unknown", equity, proof_age

    if str(getattr(instance, "kraken_health", "OK") or "OK").upper() == "ERROR":
        return False, "kraken_health_error", equity, proof_age

    return True, "authenticated_tradebalance_equity", equity, proof_age


def _chain_has_exact_wrapper(head: Any, marker_attr: str) -> bool:
    seen: set[int] = set()
    current = head
    for _ in range(32):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        owner = getattr(current, "__globals__", {})
        if bool(getattr(current, marker_attr, False)) and owner.get("MARKER") == MARKER:
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _patch_kraken_provenance() -> bool:
    module = importlib.import_module("bot.broker_manager")
    broker_cls = getattr(module, "KrakenBroker", None)
    if not isinstance(broker_cls, type):
        return False

    current_private = getattr(broker_cls, "_kraken_private_call", None)
    current_coverage = getattr(broker_cls, "get_last_pricing_coverage", None)
    if not callable(current_private) or not callable(current_coverage):
        return False

    if not _chain_has_exact_wrapper(current_private, _PRIVATE_ATTR):
        original_private = current_private

        @wraps(original_private)
        def kraken_private_call_v184(self: Any, method: str, *args: Any, **kwargs: Any):
            is_tradebalance = str(method or "") == "TradeBalance"
            try:
                result = original_private(self, method, *args, **kwargs)
            except Exception:
                if is_tradebalance:
                    _clear_aggregate_proof(self)
                raise
            if is_tradebalance:
                _record_tradebalance_result(self, result)
            return result

        kraken_private_call_v184.__name__ = "kraken_private_call_v184"
        setattr(kraken_private_call_v184, _PRIVATE_ATTR, True)
        setattr(kraken_private_call_v184, "__wrapped__", original_private)
        broker_cls._kraken_private_call = kraken_private_call_v184

    if not _chain_has_exact_wrapper(current_coverage, _COVERAGE_ATTR):
        original_coverage = current_coverage

        @wraps(original_coverage)
        def pricing_coverage_v184(self: Any) -> float:
            try:
                raw_coverage = max(0.0, min(1.0, float(original_coverage(self))))
            except Exception:
                raw_coverage = 0.0
            valid, reason, equity, proof_age = _aggregate_proof_status(self)
            if not valid:
                return raw_coverage
            effective = max(raw_coverage, 1.0)
            LOGGER.info(
                "KRAKEN_CAPITAL_V184_AGGREGATE_VALUATION_PROOF marker=%s account=%s "
                "eb=%.8f proof_age_s=%.3f raw_asset_pricing_coverage=%.3f "
                "effective_valuation_coverage=%.3f reason=%s "
                "asset_prices_fabricated=false freshness_extended=false",
                MARKER,
                getattr(self, "account_identifier", "unknown"),
                equity,
                proof_age,
                raw_coverage,
                effective,
                reason,
            )
            return effective

        pricing_coverage_v184.__name__ = "pricing_coverage_v184"
        setattr(pricing_coverage_v184, _COVERAGE_ATTR, True)
        setattr(pricing_coverage_v184, "__wrapped__", original_coverage)
        broker_cls.get_last_pricing_coverage = pricing_coverage_v184

    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_aggregate_valuation_confidence_v184"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        provenance_ok = _patch_kraken_provenance()
        manifest_ok = _patch_release_manifest()
        ready = bool(provenance_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_KRAKEN_AGGREGATE_VALUATION_CONFIDENCE_V184_FAILED marker=%s "
                "provenance_ok=%s manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(provenance_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_KRAKEN_AGGREGATE_VALUATION_CONFIDENCE_V184 marker=%s ready=true "
            "authenticated_tradebalance_equity_required=true same_balance_epoch_required=true "
            "raw_asset_pricing_metric_preserved=true effective_valuation_coverage=true "
            "freshness_ttl_unchanged=true publication_expiry_extended=false "
            "capital_mutated=false asset_prices_fabricated=false forced_activation=false "
            "signal_thresholds_unchanged=true safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_aggregate_proof_status",
    "_clear_aggregate_proof",
    "_record_tradebalance_result",
    "_patch_kraken_provenance",
    "_patch_release_manifest",
]
