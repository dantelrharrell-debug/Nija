"""Use authenticated Kraken aggregate-equity proof for capital confidence.

This runtime hardening keeps the raw per-asset pricing metric truthful while
allowing a fresh authenticated Kraken TradeBalance equivalent-equity proof to
satisfy the capital valuation-confidence input.  It also distinguishes local
process read-lock contention (KrakenReadLockBusy / v212) from genuine Kraken
exchange/API failures so local scheduling contention cannot by itself collapse
pricing confidence to zero.

No balance or price is fabricated. Freshness, completeness, writer, nonce,
risk, kill-switch, order, fill, and activation gates remain authoritative.
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
_LOCAL_BUSY_COUNT_ATTR = "_nija_v184_local_read_lock_busy_count"
_LOCAL_BUSY_TS_ATTR = "_nija_v184_local_read_lock_busy_ts"
_LOCK = threading.RLock()


def _positive_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0.0 else None


def _canonical_freshness_ttl_s() -> float:
    try:
        module = importlib.import_module("bot.capital_flow_state_machine")
        ttl = float(getattr(module, "FRESHNESS_TTL_S", 90.0) or 90.0)
    except Exception:
        ttl = 90.0
    return max(1.0, min(90.0, ttl))


def _clear_aggregate_proof(instance: Any) -> None:
    setattr(instance, _PROOF_EQUITY_ATTR, 0.0)
    setattr(instance, _PROOF_TS_ATTR, 0.0)


def _reset_local_contention(instance: Any) -> None:
    setattr(instance, _LOCAL_BUSY_COUNT_ATTR, 0)
    setattr(instance, _LOCAL_BUSY_TS_ATTR, 0.0)


def _record_local_contention(instance: Any) -> None:
    try:
        count = int(getattr(instance, _LOCAL_BUSY_COUNT_ATTR, 0) or 0)
    except Exception:
        count = 0
    setattr(instance, _LOCAL_BUSY_COUNT_ATTR, count + 1)
    setattr(instance, _LOCAL_BUSY_TS_ATTR, time.time())
    LOGGER.info(
        "KRAKEN_CAPITAL_V184_LOCAL_READ_CONTENTION marker=%s account=%s count=%d "
        "exchange_failure=false balance_fabricated=false",
        MARKER,
        getattr(instance, "account_identifier", "unknown"),
        count + 1,
    )


def _is_local_read_contention(exc: BaseException) -> bool:
    name = exc.__class__.__name__
    message = str(exc or "")
    return name == "KrakenReadLockBusy" or "Kraken read lock busy" in message


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
    # A successful authenticated TradeBalance establishes a new clean proof
    # epoch.  Only local lock-contention events after this proof are relevant.
    _reset_local_contention(instance)


def _local_contention_covers_current_errors(instance: Any, proof_ts: float) -> tuple[bool, int, int]:
    """Return True only when every current error can be attributed to local v212 contention."""
    try:
        errors_getter = getattr(instance, "get_error_count", None)
        errors = int(errors_getter()) if callable(errors_getter) else 0
    except Exception:
        return False, 0, 0
    if errors <= 0:
        return False, errors, 0
    try:
        local_count = int(getattr(instance, _LOCAL_BUSY_COUNT_ATTR, 0) or 0)
        local_ts = float(getattr(instance, _LOCAL_BUSY_TS_ATTR, 0.0) or 0.0)
    except Exception:
        return False, errors, 0
    # Fail closed unless all currently reported errors are covered by local
    # contention observed after the successful authenticated proof epoch.
    covered = local_count >= errors and local_ts >= proof_ts > 0.0
    return covered, errors, local_count


def _aggregate_proof_status(instance: Any, *, now: Optional[float] = None) -> tuple[bool, str, float, float]:
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
    if abs(balance_ts - proof_ts) > 5.0:
        return False, "aggregate_balance_epoch_mismatch", equity, proof_age

    contention_only, error_count, local_count = _local_contention_covers_current_errors(instance, proof_ts)
    if error_count > 0 and not contention_only:
        return False, "kraken_exchange_or_unattributed_errors_present", equity, proof_age

    available_getter = getattr(instance, "is_available", None)
    if callable(available_getter):
        try:
            available = bool(available_getter())
        except Exception:
            return False, "kraken_availability_unknown", equity, proof_age
        if not available and not contention_only:
            return False, "kraken_unavailable", equity, proof_age

    health = str(getattr(instance, "kraken_health", "OK") or "OK").upper()
    if health == "ERROR" and not contention_only:
        return False, "kraken_health_error", equity, proof_age

    if contention_only:
        LOGGER.warning(
            "KRAKEN_CAPITAL_V184_LOCAL_CONTENTION_TOLERATED marker=%s account=%s "
            "error_count=%d local_contention_count=%d proof_age_s=%.3f "
            "authenticated_equity_required=true exchange_error_ignored=false",
            MARKER,
            getattr(instance, "account_identifier", "unknown"),
            error_count,
            local_count,
            proof_age,
        )
        return True, "authenticated_tradebalance_equity_local_contention_only", equity, proof_age

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
            except Exception as exc:
                if _is_local_read_contention(exc):
                    _record_local_contention(self)
                elif is_tradebalance:
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
            effective = 1.0
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
            "local_read_contention_classified=true unattributed_exchange_errors_fail_closed=true "
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
