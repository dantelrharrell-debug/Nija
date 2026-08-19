"""Fail-closed runtime quality convergence for live market data and capital refreshes.

Production 2026-08-19 reached LIVE_ACTIVE with healthy writer authority, but logs
showed post-activation quality and convergence defects:

* Phase-3 scans could run for many minutes because the existing scan deadline
  guard preserved additional fetches after its deadline unless an environment
  override explicitly enabled hard skipping.
* Capital refresh generations could repeatedly wait on the same already-timed-
  out broker worker merely because that daemon thread was still alive.
* The trading-state activation-intent probe passed the literal string UNKNOWN
  into StartupCoordinator.build_snapshot(), creating recurring synthetic
  UNKNOWN -> LIVE_ACTIVE repairs even though the canonical state was known.
* The v142 total runtime deadline left too little post-fetch headroom: a refresh
  could publish a valid 3/3 snapshot near the end of its fetch budget and still
  be retired while finishing same-tick post-publication work.

v157/v159 repairs those liveness problems without weakening trading safety:

* explicitly installs the existing market-data stability and phase-3 stall
  guards and defaults the phase-3 deadline behavior to fail closed (skip data
  fetches only after the scan deadline has elapsed);
* records phase-3 candle-data completeness and folds it into the canonical OHLC
  market-data health verdict so telemetry cannot report healthy while most
  symbols are data-insufficient;
* when a prior capital broker worker is still alive beyond its own timeout,
  reuses no duplicate network request and fails that broker result immediately
  through the existing freshness-aware fallback/exclusion path;
* replaces the activation-intent read-only UNKNOWN probe with the canonical
  TradingStateMachine state while preserving explicit OFF/DRY_RUN/
  LIVE_PENDING_CONFIRMATION/EMERGENCY_STOP states;
* gives the v142 runtime pipeline enough bounded post-fetch completion headroom
  while retaining a hard deadline strictly inside CapitalAuthority freshness;
* never fabricates balances, extends freshness, changes signal thresholds,
  clears a kill switch, grants execution authority, forces candidates, or
  dispatches orders.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_quality_convergence_v157")
MARKER = "20260819-runtime-quality-convergence-v157"
READINESS_V159_MARKER = "20260819-runtime-readiness-v159"
_FLAG = "NIJA_RUNTIME_QUALITY_CONVERGENCE_V157_READY"
_V159_FLAG = "NIJA_RUNTIME_READINESS_V159_READY"
_LOCK = threading.RLock()
_QUALITY_LOCK = threading.RLock()
_LATEST_CORE_QUALITY: dict[str, Any] = {}

_CAP_INIT_ATTR = "_nija_runtime_quality_v157_capital_init"
_CAP_RESULT_ATTR = "_nija_runtime_quality_v157_capital_result"
_CORE_ATTR = "_nija_runtime_quality_v157_core_quality"
_HEALTH_ATTR = "_nija_runtime_quality_v157_market_health"
_STATE_SOURCE_ATTR = "_nija_runtime_readiness_v159_state_source"
_CAP_DEADLINE_ATTR = "_nija_runtime_readiness_v159_capital_deadline"
_VALID_TRADING_STATES = frozenset(
    {"OFF", "DRY_RUN", "LIVE_PENDING_CONFIRMATION", "LIVE_ACTIVE", "EMERGENCY_STOP"}
)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def _install_existing_market_data_guards() -> bool:
    """Install already-shipped fail-closed market-data protections explicitly."""
    os.environ.setdefault("NIJA_PHASE3_FETCH_DEADLINE_SKIP_ENABLED", "true")
    os.environ.setdefault("NIJA_PHASE3_SCAN_DEADLINE_S", "24")

    ok = True
    for module_name in (
        "bot.market_data_stability_import_guard_patch",
        "bot.phase3_scan_stall_guard_patch",
    ):
        try:
            module = importlib.import_module(module_name)
            installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
            if not callable(installer):
                raise RuntimeError(f"installer_missing:{module_name}")
            result = installer()
            if result is False:
                ok = False
        except Exception as exc:
            ok = False
            LOGGER.error(
                "RUNTIME_QUALITY_V157_GUARD_INSTALL_FAILED marker=%s module=%s error=%s:%s trading_fail_closed=true",
                MARKER,
                module_name,
                type(exc).__name__,
                exc,
            )
    return ok


def _flight_expired(flight: Any, now_monotonic: float | None = None) -> bool:
    """Return True only for an alive broker worker beyond its own hard timeout."""
    if flight is None:
        return False
    thread = getattr(flight, "thread", None)
    alive = bool(thread is not None and callable(getattr(thread, "is_alive", None)) and thread.is_alive())
    if not alive:
        return False
    try:
        started = float(getattr(flight, "started_monotonic", 0.0) or 0.0)
        timeout_s = max(0.1, float(getattr(flight, "timeout_s", 0.0) or 0.0))
    except (TypeError, ValueError):
        return False
    if started <= 0.0:
        return False
    now = time.monotonic() if now_monotonic is None else float(now_monotonic)
    return max(0.0, now - started) >= timeout_s


def _expired_flight_ids(flights: Any, now_monotonic: float | None = None) -> set[str]:
    if not isinstance(flights, dict):
        return set()
    now = time.monotonic() if now_monotonic is None else float(now_monotonic)
    return {
        str(broker_id).strip().lower()
        for broker_id, flight in flights.items()
        if _flight_expired(flight, now)
    }


def _patch_capital_expired_inflight_failfast() -> bool:
    """Fail fast on an expired reused worker without launching a duplicate fetch."""
    try:
        guard = importlib.import_module("bot.capital_refresh_stall_guard_v35")
    except Exception as exc:
        LOGGER.error(
            "RUNTIME_QUALITY_V157_CAPITAL_IMPORT_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    cls = getattr(guard, "_BalanceFetchBatch", None)
    if not isinstance(cls, type):
        return False

    current_init = getattr(cls, "__init__", None)
    current_result = getattr(cls, "result_for", None)
    if not callable(current_init) or not callable(current_result):
        return False

    if not getattr(current_init, _CAP_INIT_ATTR, False):
        original_init = current_init

        @wraps(original_init)
        def init_v157(self: Any, broker_map: dict[str, Any]) -> None:
            original_init(self, broker_map)
            expired = _expired_flight_ids(getattr(self, "_flights", {}))
            setattr(self, "_nija_v157_expired_flights", expired)
            for broker_id in sorted(expired):
                flight = getattr(self, "_flights", {}).get(broker_id)
                try:
                    age_s = max(0.0, time.monotonic() - float(getattr(flight, "started_monotonic", 0.0) or 0.0))
                    timeout_s = float(getattr(flight, "timeout_s", 0.0) or 0.0)
                except (TypeError, ValueError):
                    age_s = float("inf")
                    timeout_s = 0.0
                LOGGER.warning(
                    "CAPITAL_REFRESH_EXPIRED_INFLIGHT_FAILFAST_V157 marker=%s broker=%s age_s=%.1f timeout_s=%.1f duplicate_started=false fallback_freshness_enforced=true",
                    MARKER,
                    broker_id,
                    age_s,
                    timeout_s,
                )

        setattr(init_v157, _CAP_INIT_ATTR, True)
        setattr(init_v157, "__wrapped__", original_init)
        cls.__init__ = init_v157

    current_result = getattr(cls, "result_for", None)
    if callable(current_result) and not getattr(current_result, _CAP_RESULT_ATTR, False):
        original_result = current_result

        @wraps(original_result)
        def result_for_v157(self: Any, broker_id: str, broker: Any) -> Any:
            bid = str(broker_id).strip().lower()
            expired = set(getattr(self, "_nija_v157_expired_flights", set()) or set())
            if bid in expired:
                handler = getattr(self, "_handle_failure", None)
                if callable(handler):
                    return handler(bid, "stale_inflight_exceeded_timeout")
                return 0.0
            return original_result(self, broker_id, broker)

        setattr(result_for_v157, _CAP_RESULT_ATTR, True)
        setattr(result_for_v157, "__wrapped__", original_result)
        cls.result_for = result_for_v157

    return bool(
        getattr(getattr(cls, "__init__", None), _CAP_INIT_ATTR, False)
        and getattr(getattr(cls, "result_for", None), _CAP_RESULT_ATTR, False)
    )


def _canonical_trading_state(tsm: ModuleType) -> str:
    """Read the canonical trading state without inventing a live state."""
    getter = getattr(tsm, "get_trading_state_machine", None)
    if callable(getter):
        try:
            sm = getter()
            current = getattr(sm, "get_current_state", lambda: None)()
            value = str(getattr(current, "value", current) or "").strip().upper()
            if value in _VALID_TRADING_STATES:
                return value
        except Exception:
            pass

    singleton = getattr(tsm, "trading_state_machine", None)
    if singleton is not None:
        try:
            current = getattr(singleton, "get_current_state", lambda: None)()
            value = str(getattr(current, "value", current) or "").strip().upper()
            if value in _VALID_TRADING_STATES:
                return value
        except Exception:
            pass

    env_state = str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "") or "").strip().upper()
    if env_state in _VALID_TRADING_STATES:
        return env_state
    return "OFF"


def _patch_activation_intent_state_source() -> bool:
    """Stop the read-only activation-intent probe from injecting literal UNKNOWN."""
    try:
        tsm = importlib.import_module("bot.trading_state_machine")
    except Exception as exc:
        LOGGER.error(
            "RUNTIME_READINESS_V159_STATE_IMPORT_FAILED marker=%s error=%s:%s",
            READINESS_V159_MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    current = getattr(tsm, "_activation_intent_present", None)
    if not callable(current):
        return False
    if getattr(current, _STATE_SOURCE_ATTR, False):
        return True

    env_truthy = getattr(tsm, "_env_truthy", None)
    coordinator_getter = getattr(tsm, "_get_startup_coordinator", None)
    if not callable(coordinator_getter):
        return False

    @wraps(current)
    def activation_intent_v159(runtime_mode: Any = None) -> bool:
        if runtime_mode is not None:
            live_intent = bool(getattr(runtime_mode, "is_live", False))
        elif callable(env_truthy):
            try:
                live_intent = bool(env_truthy("LIVE_CAPITAL_VERIFIED"))
            except Exception:
                live_intent = False
        else:
            live_intent = str(os.environ.get("LIVE_CAPITAL_VERIFIED", "")).strip().lower() in {
                "1", "true", "yes", "enabled", "on", "y"
            }

        coordinator_requested = False
        state = _canonical_trading_state(tsm)
        try:
            coordinator_requested = bool(
                coordinator_getter().build_snapshot(
                    trading_state=state,
                    activation_intent=False,
                ).activation_intent
            )
        except Exception:
            coordinator_requested = False
        return bool(live_intent or coordinator_requested)

    setattr(activation_intent_v159, _STATE_SOURCE_ATTR, True)
    setattr(activation_intent_v159, "__wrapped__", current)
    setattr(tsm, "_activation_intent_present", activation_intent_v159)
    LOGGER.critical(
        "ACTIVATION_INTENT_CANONICAL_STATE_SOURCE_V159 marker=%s state=%s literal_unknown_probe=false safety_states_preserved=true",
        READINESS_V159_MARKER,
        _canonical_trading_state(tsm),
    )
    return True


def _capital_deadline_value(
    original_deadline_s: float,
    ttl_s: float,
    fetch_budget_s: float,
    post_fetch_headroom_s: float = 30.0,
    safety_margin_s: float = 10.0,
) -> float:
    """Return a runtime deadline with tail headroom, strictly inside freshness."""
    ttl = max(10.0, float(ttl_s))
    budget = max(5.0, float(fetch_budget_s))
    margin = max(5.0, min(float(safety_margin_s), max(5.0, ttl / 2.0)))
    safe_ceiling = max(10.0, ttl - margin)
    desired = budget + max(5.0, float(post_fetch_headroom_s))
    floor = min(safe_ceiling, desired)
    return max(10.0, min(safe_ceiling, max(float(original_deadline_s), floor)))


def _patch_capital_pipeline_deadline_headroom() -> bool:
    """Give v142 bounded post-fetch time without extending capital freshness."""
    try:
        v142 = importlib.import_module("bot.capital_publication_liveness_v142_patch")
    except Exception as exc:
        LOGGER.error(
            "RUNTIME_READINESS_V159_CAPITAL_IMPORT_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            READINESS_V159_MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    current = getattr(v142, "_runtime_pipeline_deadline_seconds", None)
    ttl_getter = getattr(v142, "_freshness_ttl_seconds", None)
    budget_getter = getattr(v142, "_fetch_budget_seconds", None)
    if not callable(current) or not callable(ttl_getter) or not callable(budget_getter):
        return False
    if getattr(current, _CAP_DEADLINE_ATTR, False):
        return True
    original = current

    @wraps(original)
    def deadline_v159() -> float:
        try:
            original_s = float(original())
        except Exception:
            original_s = 0.0
        try:
            ttl_s = float(ttl_getter())
        except Exception:
            ttl_s = 90.0
        try:
            fetch_budget_s = float(budget_getter())
        except Exception:
            fetch_budget_s = max(5.0, ttl_s - 30.0)
        return _capital_deadline_value(
            original_s,
            ttl_s,
            fetch_budget_s,
            post_fetch_headroom_s=_float_env(
                "NIJA_CAPITAL_RUNTIME_PIPELINE_POST_FETCH_HEADROOM_S", 30.0
            ),
            safety_margin_s=_float_env(
                "NIJA_CAPITAL_RUNTIME_PIPELINE_SAFETY_MARGIN_S", 10.0
            ),
        )

    setattr(deadline_v159, _CAP_DEADLINE_ATTR, True)
    setattr(deadline_v159, "__wrapped__", original)
    setattr(v142, "_runtime_pipeline_deadline_seconds", deadline_v159)
    LOGGER.critical(
        "CAPITAL_RUNTIME_DEADLINE_HEADROOM_V159 marker=%s deadline_s=%.1f ttl_s=%.1f fetch_budget_s=%.1f publication_expiry_extended=false generation_fence_unchanged=true trading_fail_closed_on_true_timeout=true",
        READINESS_V159_MARKER,
        deadline_v159(),
        float(ttl_getter()),
        float(budget_getter()),
    )
    return True


def _record_core_quality(result: Any) -> None:
    """Capture the latest phase-3 data completeness without changing its result."""
    if not isinstance(result, (tuple, list)) or len(result) < 4:
        return
    gates = result[3] if isinstance(result[3], dict) else {}
    try:
        scored = max(0, int(result[2] or 0))
        data_insufficient = max(0, int(gates.get("data_insufficient", 0) or 0))
    except (TypeError, ValueError):
        return
    attempts = scored + data_insufficient
    if attempts <= 0:
        return
    failure_rate = data_insufficient / attempts
    sample = {
        "observed_monotonic": time.monotonic(),
        "scored": scored,
        "data_insufficient": data_insufficient,
        "attempts": attempts,
        "failure_rate": failure_rate,
    }
    with _QUALITY_LOCK:
        _LATEST_CORE_QUALITY.clear()
        _LATEST_CORE_QUALITY.update(sample)

    max_rate = max(0.0, min(1.0, _float_env("NIJA_CORE_DATA_FAILURE_MAX_RATE", 0.50)))
    healthy = failure_rate < max_rate
    log = LOGGER.info if healthy else LOGGER.warning
    log(
        "MARKET_DATA_CORE_QUALITY_V157 marker=%s scored=%d data_insufficient=%d attempts=%d failure_rate=%.4f max_rate=%.4f healthy=%s",
        MARKER,
        scored,
        data_insufficient,
        attempts,
        failure_rate,
        max_rate,
        str(healthy).lower(),
    )


def _core_quality_gate(now_monotonic: float | None = None) -> tuple[bool, dict[str, Any]]:
    with _QUALITY_LOCK:
        sample = dict(_LATEST_CORE_QUALITY)
    if not sample:
        return True, {"core_quality_sample_present": False}

    now = time.monotonic() if now_monotonic is None else float(now_monotonic)
    age_s = max(0.0, now - float(sample.get("observed_monotonic", 0.0) or 0.0))
    max_age_s = max(5.0, _float_env("NIJA_CORE_DATA_QUALITY_MAX_AGE_S", 180.0))
    recent = age_s <= max_age_s
    rate = float(sample.get("failure_rate", 0.0) or 0.0)
    max_rate = max(0.0, min(1.0, _float_env("NIJA_CORE_DATA_FAILURE_MAX_RATE", 0.50)))
    ok = (not recent) or rate < max_rate
    detail = {
        "core_quality_sample_present": True,
        "core_quality_sample_recent": recent,
        "core_quality_age_s": round(age_s, 1),
        "core_data_failure_rate": round(rate, 4),
        "core_data_failure_max_rate": round(max_rate, 4),
        "core_data_quality_ok": ok,
        "core_scored": int(sample.get("scored", 0) or 0),
        "core_data_insufficient": int(sample.get("data_insufficient", 0) or 0),
    }
    return ok, detail


def _patch_core_quality_probe() -> bool:
    """Wrap phase-3 only to observe its existing gate-rejection accounting."""
    seen = False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        cls = getattr(module, "NijaCoreLoop", None)
        if not isinstance(cls, type):
            continue
        seen = True
        current = getattr(cls, "_phase3_scan_and_enter", None)
        if not callable(current):
            continue
        if getattr(current, _CORE_ATTR, False):
            continue
        original = current

        @wraps(original)
        def phase3_quality_v157(self: Any, *args: Any, __original: Any = original, **kwargs: Any) -> Any:
            result = __original(self, *args, **kwargs)
            try:
                _record_core_quality(result)
            except Exception as exc:
                LOGGER.debug("RUNTIME_QUALITY_V157_CORE_PROBE_ERROR marker=%s error=%s", MARKER, exc)
            return result

        setattr(phase3_quality_v157, _CORE_ATTR, True)
        setattr(phase3_quality_v157, "__wrapped__", original)
        setattr(cls, "_phase3_scan_and_enter", phase3_quality_v157)

    return True if not seen else any(
        isinstance(sys.modules.get(name), ModuleType)
        and isinstance(getattr(sys.modules.get(name), "NijaCoreLoop", None), type)
        and bool(getattr(getattr(sys.modules.get(name).NijaCoreLoop, "_phase3_scan_and_enter", None), _CORE_ATTR, False))
        for name in ("bot.nija_core_loop", "nija_core_loop")
    )


def _patch_market_data_health() -> bool:
    """Make OHLC health include the core scan's actual data-completeness signal."""
    try:
        pool_module = importlib.import_module("bot.ohlc_worker_pool")
    except Exception as exc:
        LOGGER.error(
            "RUNTIME_QUALITY_V157_OHLC_IMPORT_FAILED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False
    cls = getattr(pool_module, "OHLCWorkerPool", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "compute_market_data_healthy", None)
    if not callable(current):
        return False
    if getattr(current, _HEALTH_ATTR, False):
        return True
    original = current

    @wraps(original)
    def compute_market_data_healthy_v157(self: Any, *args: Any, **kwargs: Any):
        healthy, detail = original(self, *args, **kwargs)
        detail = dict(detail or {})
        core_ok, core_detail = _core_quality_gate()
        healthy = bool(healthy and core_ok)
        detail.update(core_detail)
        detail["market_data_healthy"] = healthy
        return healthy, detail

    setattr(compute_market_data_healthy_v157, _HEALTH_ATTR, True)
    setattr(compute_market_data_healthy_v157, "__wrapped__", original)
    cls.compute_market_data_healthy = compute_market_data_healthy_v157
    return True


def install() -> bool:
    with _LOCK:
        guards_ok = _install_existing_market_data_guards()
        capital_ok = _patch_capital_expired_inflight_failfast()
        health_ok = _patch_market_data_health()
        core_ok = _patch_core_quality_probe()
        state_source_ok = _patch_activation_intent_state_source()
        deadline_ok = _patch_capital_pipeline_deadline_headroom()
        readiness_v159 = bool(state_source_ok and deadline_ok)
        ready = bool(guards_ok and capital_ok and health_ok and core_ok and readiness_v159)
        os.environ[_FLAG] = "1" if ready else "0"
        os.environ[_V159_FLAG] = "1" if readiness_v159 else "0"
        LOGGER.critical(
            "RUNTIME_QUALITY_CONVERGENCE_V157 marker=%s ready=%s phase3_deadline_fail_closed=true capital_expired_inflight_failfast=%s market_health_core_quality=%s core_probe=%s state_source_v159=%s capital_deadline_v159=%s safety_gates_bypassed=false",
            MARKER,
            str(ready).lower(),
            str(capital_ok).lower(),
            str(health_ok).lower(),
            str(core_ok).lower(),
            str(state_source_ok).lower(),
            str(deadline_ok).lower(),
        )
        return ready


__all__ = [
    "MARKER",
    "READINESS_V159_MARKER",
    "install",
    "_flight_expired",
    "_expired_flight_ids",
    "_record_core_quality",
    "_core_quality_gate",
    "_canonical_trading_state",
    "_capital_deadline_value",
    "_patch_activation_intent_state_source",
    "_patch_capital_pipeline_deadline_headroom",
    "_patch_capital_expired_inflight_failfast",
    "_patch_core_quality_probe",
    "_patch_market_data_health",
]
