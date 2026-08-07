"""Capital refresh sticky-success hotfix v37.

Repairs the v36 stall guard without weakening freshness or first-snapshot gates.

Root cause addressed
--------------------
Bootstrap/connection code may successfully hydrate ``_last_known_balance`` and
mark a broker PAYLOAD_READY before ``CapitalRefreshCoordinator`` starts.  The
v36 stall guard only records observations made by its own bounded worker, so a
second API call can time out and incorrectly classify that already-hydrated
broker as having no usable payload.  A second read of the same bounded proxy can
also drain the one-item result queue and later appear to time out.

This hotfix:
* captures successful platform-broker balance reads before the coordinator;
* binds all v35/v36 import aliases to the same guard module/state;
* makes a successful/fallback payload sticky for the remainder of a batch;
* preserves monotonic age/deadline calculations and original observation age;
* emits explicit begin/success/timeout/decision/final telemetry;
* only emits TIMEOUT_EXCLUDED when a real timeout has no usable fresh payload.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import math
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Dict, Optional

logger = logging.getLogger("nija.capital_refresh_sticky_success_v37")
MARKER = "20260807-capital-refresh-sticky-success-v37"
_GUARD_NAMES = (
    "nija_capital_refresh_stall_guard_v35_prebot",
    "bot.capital_refresh_stall_guard_v35",
    "capital_refresh_stall_guard_v35",
)
_FLOW_NAMES = ("bot.capital_flow_state_machine", "capital_flow_state_machine")
_BROKER_NAMES = ("bot.broker_manager", "broker_manager")
_BROKER_CLASSES = {
    "CoinbaseBroker": "coinbase",
    "KrakenBroker": "kraken",
    "OKXBroker": "okx",
    "AlpacaBroker": "alpaca",
}
_LOCK = threading.RLock()
_CTX = threading.local()
_INSTALLED = False
_CYCLE = 0
_CYCLE_LOCK = threading.Lock()
_HOOK_FLAG = "_NIJA_CAPITAL_REFRESH_STICKY_SUCCESS_V37_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_CAPITAL_REFRESH_STICKY_SUCCESS_V37_IMPORTLIB_HOOK"
_BROKER_WRAP_ATTR = "_nija_capital_refresh_v37_success_observer"
_PIPELINE_WRAP_ATTR = "_nija_capital_refresh_v37_telemetry"


def _next_cycle() -> int:
    global _CYCLE
    with _CYCLE_LOCK:
        _CYCLE += 1
        return _CYCLE


def _guard() -> Optional[ModuleType]:
    for name in _GUARD_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            sys.modules.setdefault("capital_refresh_stall_guard_v35", module)
            sys.modules.setdefault("bot.capital_refresh_stall_guard_v35", module)
            return module
    return None


def _scalar(value: Any) -> Optional[float]:
    try:
        if isinstance(value, dict):
            value = (
                value.get("trading_balance")
                or value.get("total_funds")
                or value.get("total_balance")
                or (float(value.get("usd", 0.0) or 0.0) + float(value.get("usdc", 0.0) or 0.0))
                or 0.0
            )
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(result) or result < 0.0:
        return None
    return result


def _wall_ts(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        result = float(value.timestamp()) if hasattr(value, "timestamp") else float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) and result > 0.0 else None


def _broker_id(instance: Any, fallback: str) -> str:
    candidates = (
        getattr(getattr(instance, "broker_type", None), "value", None),
        getattr(instance, "name", None),
        fallback,
    )
    for candidate in candidates:
        text = str(candidate or "").strip().lower()
        for name in ("coinbase", "kraken", "okx", "alpaca"):
            if name in text:
                return name
    return str(fallback).strip().lower()


def _is_platform(instance: Any) -> bool:
    account_type = getattr(instance, "account_type", None)
    text = str(getattr(account_type, "value", account_type) or "").strip().lower()
    if not text:
        return True
    return "user" not in text


def _record_observation(
    guard: ModuleType,
    broker_id: str,
    value: float,
    observed_mono: float,
    observed_epoch: float,
    source: str,
) -> None:
    sequence = int(getattr(guard, "_BROKER_SEQUENCE", {}).get(broker_id, 0))
    observation_cls = getattr(guard, "_Observation", None)
    if observation_cls is None:
        return
    try:
        observation = observation_cls(value, observed_mono, observed_epoch, sequence)
    except TypeError:
        observation = observation_cls(
            value=value,
            observed_monotonic=observed_mono,
            observed_epoch=observed_epoch,
            sequence=sequence,
        )
    lock = getattr(guard, "_OBSERVATION_LOCK", None)
    observations = getattr(guard, "_OBSERVATIONS", None)
    if not isinstance(observations, dict):
        return
    if lock is None:
        observations[broker_id] = observation
        return
    with lock:
        previous = observations.get(broker_id)
        previous_mono = float(getattr(previous, "observed_monotonic", 0.0) or 0.0)
        if previous is None or observed_mono >= previous_mono:
            observations[broker_id] = observation


def _capture_success(instance: Any, broker_id: str, raw: Any, started_mono: float, finished_mono: float, finished_epoch: float) -> None:
    guard = _guard()
    if guard is None or not _is_platform(instance):
        return
    value = _scalar(raw)
    if value is None:
        return

    observed_epoch = _wall_ts(getattr(instance, "_balance_last_updated", None))
    getter = getattr(instance, "get_balance_fetch_timestamp", None)
    if observed_epoch is None and callable(getter):
        try:
            observed_epoch = _wall_ts(getter())
        except Exception:
            observed_epoch = None

    if observed_epoch is not None:
        wall_age = max(0.0, finished_epoch - observed_epoch)
        observed_mono = max(0.0, finished_mono - wall_age)
        source = "broker_success_timestamped"
    else:
        try:
            errors = int(getattr(instance, "_balance_fetch_errors"))
        except (TypeError, ValueError, AttributeError):
            errors = -1
        if errors != 0:
            return
        observed_mono = finished_mono
        observed_epoch = finished_epoch
        source = "broker_success_clean_state"

    _record_observation(guard, broker_id, value, observed_mono, observed_epoch, source)
    logger.info(
        "CAPITAL_REFRESH_FETCH_SUCCESS marker=%s cycle_id=%s broker=%s latency=%.3f timestamp=%.6f source=%s",
        MARKER,
        getattr(_CTX, "cycle_id", "external"),
        broker_id,
        max(0.0, finished_mono - started_mono),
        observed_epoch,
        source,
    )


def _patch_brokers(module: ModuleType) -> bool:
    changed = False
    for class_name, fallback in _BROKER_CLASSES.items():
        cls = getattr(module, class_name, None)
        if not isinstance(cls, type):
            continue
        original = getattr(cls, "get_account_balance", None)
        if not callable(original) or getattr(original, _BROKER_WRAP_ATTR, False):
            continue

        @wraps(original)
        def wrapped(self: Any, *args: Any, __original: Any = original, __fallback: str = fallback, **kwargs: Any) -> Any:
            started = time.monotonic()
            result = __original(self, *args, **kwargs)
            finished = time.monotonic()
            if not threading.current_thread().name.startswith("capital-balance-fetch-"):
                try:
                    _capture_success(self, _broker_id(self, __fallback), result, started, finished, time.time())
                except Exception as exc:
                    logger.debug("CAPITAL_REFRESH_SUCCESS_OBSERVER_ERROR broker=%s error=%s", __fallback, exc)
            return result

        setattr(wrapped, _BROKER_WRAP_ATTR, True)
        cls.get_account_balance = wrapped
        changed = True
    if changed:
        logger.critical("CAPITAL_REFRESH_V37_BROKER_OBSERVER_PATCHED marker=%s module=%s", MARKER, module.__name__)
    return changed


def _decision(broker_id: str, include: bool, reason: str) -> None:
    decisions = dict(getattr(_CTX, "decisions", {}) or {})
    current = {"include": bool(include), "reason": str(reason)}
    if decisions.get(broker_id) != current:
        logger.info(
            "CAPITAL_REFRESH_DECISION marker=%s cycle_id=%s broker=%s include=%s reason=%s",
            MARKER,
            getattr(_CTX, "cycle_id", "external"),
            broker_id,
            str(bool(include)).lower(),
            reason,
        )
    decisions[broker_id] = current
    _CTX.decisions = decisions


def _patch_guard(guard: ModuleType) -> bool:
    batch_cls = getattr(guard, "_BalanceFetchBatch", None)
    if not isinstance(batch_cls, type):
        return False
    if getattr(batch_cls, "_nija_sticky_success_v37", False):
        return True

    original_init = batch_cls.__init__
    original_result_for = batch_cls.result_for

    @wraps(original_init)
    def init(self: Any, broker_map: Dict[str, Any]) -> None:
        self._nija_v37_resolved = {}
        self._nija_v37_lock = threading.Lock()
        original_init(self, broker_map)

    @wraps(original_result_for)
    def result_for(self: Any, broker_id: str, broker: Any) -> Any:
        bid = str(broker_id).strip().lower()
        lock = getattr(self, "_nija_v37_lock", None)
        resolved = getattr(self, "_nija_v37_resolved", {})
        if lock is not None:
            with lock:
                if bid in resolved:
                    value = resolved[bid]
                    _decision(bid, bool((_scalar(value) or 0.0) > 0.0), "same_cycle_success_preserved")
                    return value

        before_live = dict(getattr(getattr(guard, "_REFRESH_CONTEXT", object()), "live_brokers", {}) or {})
        value = original_result_for(self, bid, broker)
        scalar = _scalar(value)
        if scalar is not None and scalar > 0.0:
            if lock is not None:
                with lock:
                    resolved.setdefault(bid, value)
            after_live = dict(getattr(getattr(guard, "_REFRESH_CONTEXT", object()), "live_brokers", {}) or {})
            live_record = after_live.get(bid)
            if bid not in before_live and isinstance(live_record, dict):
                flight = getattr(self, "_flights", {}).get(bid)
                started = float(getattr(flight, "started_monotonic", time.monotonic()) or time.monotonic())
                timestamp = float(live_record.get("observed_epoch", time.time()) or time.time())
                logger.info(
                    "CAPITAL_REFRESH_FETCH_SUCCESS marker=%s cycle_id=%s broker=%s latency=%.3f timestamp=%.6f source=bounded_fetch",
                    MARKER,
                    getattr(_CTX, "cycle_id", "external"),
                    bid,
                    max(0.0, time.monotonic() - started),
                    timestamp,
                )
                _decision(bid, True, "fetch_success")
            else:
                _decision(bid, True, "last_success_preserved")
        elif scalar == 0.0:
            _decision(bid, False, "zero_balance")
        return value

    def handle_failure(self: Any, broker_id: str, reason: str) -> float:
        bid = str(broker_id).strip().lower()
        lock = getattr(self, "_nija_v37_lock", None)
        resolved = getattr(self, "_nija_v37_resolved", {})
        if lock is not None:
            with lock:
                existing = resolved.get(bid)
            if (_scalar(existing) or 0.0) > 0.0:
                _decision(bid, True, "same_cycle_success_preserved")
                return float(_scalar(existing) or 0.0)

        now = time.monotonic()
        observations = getattr(guard, "_OBSERVATIONS", {})
        obs_lock = getattr(guard, "_OBSERVATION_LOCK", None)
        if obs_lock is None:
            observation = observations.get(bid) if isinstance(observations, dict) else None
        else:
            with obs_lock:
                observation = observations.get(bid) if isinstance(observations, dict) else None
        observed_mono = float(getattr(observation, "observed_monotonic", 0.0) or 0.0)
        age_s = max(0.0, now - observed_mono) if observed_mono > 0.0 else float("inf")
        ttl_s = float(getattr(guard, "_freshness_ttl_seconds")())
        cached_value = _scalar(getattr(observation, "value", None))
        fresh = bool(cached_value is not None and cached_value > 0.0 and age_s <= ttl_s)

        if reason == "timeout":
            flight = getattr(self, "_flights", {}).get(bid)
            started = float(getattr(flight, "started_monotonic", now) or now)
            deadline = min(
                started + float(getattr(flight, "timeout_s", 0.0) or 0.0),
                float(getattr(self, "_cycle_deadline", started) or started),
            )
            logger.warning(
                "CAPITAL_REFRESH_FETCH_TIMEOUT marker=%s cycle_id=%s broker=%s elapsed=%.3f last_success_age=%s fetch_start=%.6f deadline=%.6f",
                MARKER,
                getattr(_CTX, "cycle_id", "external"),
                bid,
                max(0.0, now - started),
                "inf" if not math.isfinite(age_s) else f"{age_s:.3f}",
                started,
                deadline,
            )

        refresh = getattr(guard, "_REFRESH_CONTEXT", None)
        if refresh is not None:
            refresh.used_fallback = True

        if fresh and observation is not None:
            fallbacks = dict(getattr(refresh, "fallback_brokers", {}) or {}) if refresh is not None else {}
            fallbacks[bid] = {
                "value": float(cached_value),
                "age_s": age_s,
                "observed": True,
                "observed_epoch": float(getattr(observation, "observed_epoch", 0.0) or 0.0),
                "sequence": int(getattr(observation, "sequence", 0) or 0),
                "cached_valid": True,
                "reason": reason,
            }
            if refresh is not None:
                refresh.fallback_brokers = fallbacks
                excluded = dict(getattr(refresh, "excluded_brokers", {}) or {})
                excluded.pop(bid, None)
                refresh.excluded_brokers = excluded
            if lock is not None:
                with lock:
                    resolved.setdefault(bid, float(cached_value))
            logger.warning(
                "CAPITAL_REFRESH_BROKER_FETCH_TIMEOUT_FALLBACK marker=%s cycle_id=%s broker=%s reason=%s cached_payload=true cached_age_s=%.2f",
                MARKER,
                getattr(_CTX, "cycle_id", "external"),
                bid,
                reason,
                age_s,
            )
            _decision(bid, True, f"last_success_preserved:{reason}")
            return float(cached_value)

        if refresh is not None:
            excluded = dict(getattr(refresh, "excluded_brokers", {}) or {})
            excluded[bid] = {
                "age_s": age_s,
                "observed": observation is not None,
                "observed_epoch": float(getattr(observation, "observed_epoch", 0.0) or 0.0),
                "reason": reason,
                "cached_valid": False,
            }
            refresh.excluded_brokers = excluded
        _decision(bid, False, f"no_usable_payload:{reason}")
        if reason == "timeout":
            logger.error(
                "CAPITAL_REFRESH_BROKER_FETCH_TIMEOUT_EXCLUDED marker=%s cycle_id=%s broker=%s reason=timeout cached_payload=false cached_age_s=%s action=exclude_from_snapshot",
                MARKER,
                getattr(_CTX, "cycle_id", "external"),
                bid,
                "inf" if not math.isfinite(age_s) else f"{age_s:.2f}",
            )
        else:
            logger.error(
                "CAPITAL_REFRESH_BROKER_FETCH_FAILED_EXCLUDED marker=%s cycle_id=%s broker=%s reason=%s cached_payload=false action=exclude_from_snapshot",
                MARKER,
                getattr(_CTX, "cycle_id", "external"),
                bid,
                reason,
            )
        return 0.0

    batch_cls.__init__ = init
    batch_cls.result_for = result_for
    batch_cls._handle_failure = handle_failure
    setattr(batch_cls, "_nija_sticky_success_v37", True)
    logger.critical("CAPITAL_REFRESH_V37_STICKY_BATCH_PATCHED marker=%s", MARKER)
    return True


def _patch_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "CapitalRefreshCoordinator", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_pipeline", None)
    if not callable(original) or getattr(original, _PIPELINE_WRAP_ATTR, False):
        return False

    @wraps(original)
    def wrapped(self: Any, broker_map: Dict[str, Any], trigger: str, open_exposure_usd: float) -> Any:
        _CTX.cycle_id = _next_cycle()
        _CTX.decisions = {}
        brokers = sorted(str(name).strip().lower() for name in broker_map if broker_map.get(name) is not None)
        logger.info(
            "CAPITAL_REFRESH_BEGIN marker=%s cycle_id=%s trigger=%s brokers=%s timestamp=%.6f",
            MARKER,
            _CTX.cycle_id,
            trigger,
            brokers,
            time.time(),
        )
        result: Any = None
        try:
            result = original(self, broker_map=broker_map, trigger=trigger, open_exposure_usd=open_exposure_usd)
            return result
        finally:
            decisions = dict(getattr(_CTX, "decisions", {}) or {})
            included = sorted(name for name, row in decisions.items() if bool(row.get("include")))
            excluded = sorted(name for name, row in decisions.items() if not bool(row.get("include")))
            try:
                snapshot_total = float(getattr(result, "real_capital"))
            except (TypeError, ValueError, AttributeError):
                snapshot_total = 0.0
                guard = _guard()
                if guard is not None:
                    status_getter = getattr(guard, "current_refresh_fallback_status", None)
                    if callable(status_getter):
                        try:
                            status = dict(status_getter())
                            rows = {**dict(status.get("brokers", {}) or {}), **dict(status.get("live_brokers", {}) or {})}
                            snapshot_total = sum(float(row.get("value", 0.0) or 0.0) for row in rows.values())
                        except Exception:
                            pass
            logger.info(
                "CAPITAL_REFRESH_FINAL marker=%s cycle_id=%s included=%s excluded=%s snapshot_total=%.2f",
                MARKER,
                getattr(_CTX, "cycle_id", "external"),
                included,
                excluded,
                snapshot_total,
            )

    setattr(wrapped, _PIPELINE_WRAP_ATTR, True)
    cls._pipeline = wrapped
    logger.critical("CAPITAL_REFRESH_V37_PIPELINE_TELEMETRY_PATCHED marker=%s module=%s", MARKER, module.__name__)
    return True


def _patch_loaded() -> bool:
    changed = False
    guard = _guard()
    if guard is not None:
        changed = _patch_guard(guard) or changed
    seen: set[int] = set()
    for name in _BROKER_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_brokers(module) or changed
    seen.clear()
    for name in _FLOW_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_pipeline(module) or changed
    return changed


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                module = original_import(name, globals, locals, fromlist, level)
                text = str(name)
                if text.endswith("broker_manager") or text.endswith("capital_flow_state_machine") or text.endswith("capital_refresh_stall_guard_v35"):
                    _patch_loaded()
                return module

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module(name: str, package: str | None = None):
                module = original_import_module(name, package)
                text = str(name)
                if text.endswith("broker_manager") or text.endswith("capital_flow_state_machine") or text.endswith("capital_refresh_stall_guard_v35"):
                    _patch_loaded()
                return module

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        _INSTALLED = True
        try:
            import os
            os.environ["NIJA_CAPITAL_REFRESH_STICKY_SUCCESS_V37_INSTALLED"] = "1"
        except Exception:
            pass
        logger.critical("CAPITAL_REFRESH_STICKY_SUCCESS_V37_INSTALLED marker=%s", MARKER)
        return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook"]
