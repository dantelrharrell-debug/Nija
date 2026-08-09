"""Capital refresh stall guard v36 (compatibility filename v35).

Bounds broker balance calls without allowing timed-out work to poison the next
cycle or silently revive stale CapitalAuthority values.

Safety properties
-----------------
* one in-flight request per broker;
* a reused in-flight request reuses the SAME result queue;
* late results are sequence checked;
* only a previously confirmed successful bounded fetch may be used as fallback;
* fallback preserves the original observation timestamp and age;
* expired/untrusted fallback returns 0.0 so the coordinator excludes the broker
  instead of entering its legacy "previous authority balance" exception path;
* broker-specific timeouts remain bounded but are long enough for observed live
  authenticated balance latency (especially Coinbase and OKX);
* the batch cycle deadline is never shorter than its slowest broker deadline;
* fallback provenance is available to confidence/trace consumers;
* no balance, authority, or writer gate is synthesized or bypassed.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import math
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass
from functools import wraps
from types import ModuleType
from typing import Any, Dict, Iterable, Optional

LOGGER = logging.getLogger("nija.capital_refresh_stall_guard_v35")
MARKER = "20260807-capital-refresh-provenance-v36"
LATENCY_MARKER = "20260809-capital-refresh-live-latency-v62"
_TARGETS = ("bot.capital_flow_state_machine", "capital_flow_state_machine")
_LOCK = threading.RLock()
_STARTED = False
_REFRESH_CONTEXT = threading.local()
_HOOK_FLAG = "_NIJA_CAPITAL_REFRESH_STALL_GUARD_V36_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_CAPITAL_REFRESH_STALL_GUARD_V36_IMPORTLIB_HOOK"

if __name__ == "nija_capital_refresh_stall_guard_v35_prebot":
    sys.modules.setdefault("capital_refresh_stall_guard_v35", sys.modules[__name__])


@dataclass
class _Observation:
    value: float
    observed_monotonic: float
    observed_epoch: float
    sequence: int


@dataclass
class _Flight:
    thread: threading.Thread
    result_queue: queue.Queue
    sequence: int
    started_monotonic: float
    timeout_s: float


_IN_FLIGHT: Dict[str, _Flight] = {}
_IN_FLIGHT_LOCK = threading.Lock()
_BROKER_SEQUENCE: Dict[str, int] = {}
_OBSERVATIONS: Dict[str, _Observation] = {}
_OBSERVATION_LOCK = threading.Lock()
_LAST_TIMEOUT_LOGGED: Dict[str, float] = {}
_TIMEOUT_LOG_DEDUP_S = 30.0
_WAS_TIMING_OUT: Dict[str, bool] = {}


def _freshness_ttl_seconds() -> float:
    try:
        return max(5.0, float(os.getenv("NIJA_CAPITAL_FRESHNESS_TTL_S", "90.0") or 90.0))
    except (TypeError, ValueError):
        return 90.0


def _timeout_seconds() -> float:
    """Generic fallback timeout for unknown/low-latency brokers.

    Keep the legacy environment variable authoritative when an operator sets it,
    but use a safer 45 second default.  Production showed that an 8 second
    default deterministically excluded healthy authenticated brokers whose live
    balance calls regularly complete in tens of seconds.
    """
    try:
        return max(
            2.0,
            float(os.getenv("NIJA_CAPITAL_BROKER_FETCH_TIMEOUT_S", "45.0") or 45.0),
        )
    except (TypeError, ValueError):
        return 45.0


def _configured_broker_timeout(env_name: str, fallback_s: float) -> float:
    raw = str(os.getenv(env_name, "") or "").strip()
    if raw:
        try:
            return max(2.0, float(raw))
        except (TypeError, ValueError):
            pass
    return max(_timeout_seconds(), float(fallback_s))


def _broker_timeout_seconds(broker_id: str) -> float:
    """Return a bounded timeout matched to observed authenticated venue latency.

    These are waits for already-started daemon balance workers, not network
    retries.  They do not turn stale data into fresh data and do not bypass the
    freshness/empty-snapshot gates.  Operators can override each venue with the
    dedicated environment variable.
    """
    bid = str(broker_id).strip().lower()
    if bid == "coinbase":
        # Production has shown successful Coinbase balance calls around 144s.
        return _configured_broker_timeout("NIJA_CAPITAL_COINBASE_FETCH_TIMEOUT_S", 180.0)
    if bid == "okx":
        # Production has repeatedly shown successful OKX calls around 28-43s.
        return _configured_broker_timeout("NIJA_CAPITAL_OKX_FETCH_TIMEOUT_S", 75.0)
    if bid == "kraken":
        return _configured_broker_timeout("NIJA_CAPITAL_KRAKEN_FETCH_TIMEOUT_S", 75.0)
    return _timeout_seconds()


def _cycle_deadline_seconds(broker_ids: Optional[Iterable[str]] = None) -> float:
    """Return a bounded batch deadline that cannot undercut a broker timeout."""
    ids = [str(value).strip().lower() for value in (broker_ids or ()) if str(value).strip()]
    slowest = max((_broker_timeout_seconds(bid) for bid in ids), default=_timeout_seconds())
    minimum_cycle_s = slowest + 5.0
    raw = str(os.getenv("NIJA_CAPITAL_CYCLE_DEADLINE_S", "") or "").strip()
    if raw:
        try:
            configured = max(2.0, float(raw))
        except (TypeError, ValueError):
            configured = minimum_cycle_s
    else:
        configured = minimum_cycle_s
    # A stale legacy value such as 12s must never silently cap a 75s/180s
    # broker timeout.  The per-broker timeout remains the primary hard bound.
    return max(minimum_cycle_s, configured)


def _coerce_scalar(value: Any) -> Optional[float]:
    try:
        if isinstance(value, dict):
            scalar = float(
                value.get("trading_balance")
                or value.get("total_funds")
                or (
                    float(value.get("usd", 0.0) or 0.0)
                    + float(value.get("usdc", 0.0) or 0.0)
                )
                or 0.0
            )
        else:
            scalar = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(scalar) or scalar < 0.0:
        return None
    return scalar


def _begin_refresh_context() -> None:
    _REFRESH_CONTEXT.in_refresh = True
    _REFRESH_CONTEXT.used_fallback = False
    _REFRESH_CONTEXT.fallback_brokers = {}
    _REFRESH_CONTEXT.excluded_brokers = {}
    _REFRESH_CONTEXT.live_brokers = {}


def _status_from_context() -> Dict[str, Any]:
    used_fallback = bool(getattr(_REFRESH_CONTEXT, "used_fallback", False))
    fallbacks = dict(getattr(_REFRESH_CONTEXT, "fallback_brokers", {}) or {})
    excluded = dict(getattr(_REFRESH_CONTEXT, "excluded_brokers", {}) or {})
    live = dict(getattr(_REFRESH_CONTEXT, "live_brokers", {}) or {})
    ttl_s = _freshness_ttl_seconds()
    all_recent = bool(
        used_fallback
        and fallbacks
        and not excluded
        and all(
            bool(record.get("observed"))
            and float(record.get("age_s", float("inf"))) <= ttl_s
            for record in fallbacks.values()
        )
    )
    source = (
        "partial_or_excluded_fallback"
        if excluded
        else "cached_live_observation"
        if fallbacks
        else "live_exchange"
    )
    return {
        "used_fallback": used_fallback,
        "all_recent": all_recent,
        "freshness_ttl_s": ttl_s,
        "brokers": fallbacks,
        "excluded_brokers": excluded,
        "live_brokers": live,
        "source": source,
    }


def current_refresh_used_fallback() -> bool:
    if bool(getattr(_REFRESH_CONTEXT, "in_refresh", False)):
        return bool(getattr(_REFRESH_CONTEXT, "used_fallback", False))
    return bool(
        dict(getattr(_REFRESH_CONTEXT, "last_status", {}) or {}).get(
            "used_fallback", False
        )
    )


def current_refresh_fallback_status(
    freshness_ttl_s: Optional[float] = None,
) -> Dict[str, Any]:
    if bool(getattr(_REFRESH_CONTEXT, "in_refresh", False)):
        status = _status_from_context()
    else:
        status = dict(getattr(_REFRESH_CONTEXT, "last_status", {}) or {})
        if not status:
            status = {
                "used_fallback": False,
                "all_recent": False,
                "freshness_ttl_s": _freshness_ttl_seconds(),
                "brokers": {},
                "excluded_brokers": {},
                "live_brokers": {},
                "source": "live_exchange",
            }
    if freshness_ttl_s is not None:
        ttl_s = max(5.0, float(freshness_ttl_s))
        status["freshness_ttl_s"] = ttl_s
        fallbacks = dict(status.get("brokers", {}) or {})
        excluded = dict(status.get("excluded_brokers", {}) or {})
        status["all_recent"] = bool(
            status.get("used_fallback")
            and fallbacks
            and not excluded
            and all(
                float(v.get("age_s", float("inf"))) <= ttl_s
                for v in fallbacks.values()
            )
        )
    return status


class _BalanceFetchBatch:
    """Concurrent per-broker fetches with queue-correct in-flight reuse."""

    def __init__(self, broker_map: Dict[str, Any]) -> None:
        self._batch_started = time.monotonic()
        self._cycle_deadline = self._batch_started + _cycle_deadline_seconds(
            broker_map.keys()
        )
        self._flights: Dict[str, _Flight] = {}

        for broker_id, broker in broker_map.items():
            bid = str(broker_id).strip().lower()
            timeout_s = _broker_timeout_seconds(bid)
            with _IN_FLIGHT_LOCK:
                existing = _IN_FLIGHT.get(bid)
                if existing is not None and existing.thread.is_alive():
                    self._flights[bid] = existing
                    LOGGER.debug(
                        "CAPITAL_REFRESH_INFLIGHT_REUSED marker=%s broker=%s seq=%d age_s=%.2f timeout_s=%.1f",
                        MARKER,
                        bid,
                        existing.sequence,
                        max(0.0, time.monotonic() - existing.started_monotonic),
                        existing.timeout_s,
                    )
                    continue

                seq = _BROKER_SEQUENCE.get(bid, 0) + 1
                _BROKER_SEQUENCE[bid] = seq
                result_queue: queue.Queue = queue.Queue(maxsize=1)
                started = time.monotonic()

                def _call(
                    target: Any = broker,
                    output: queue.Queue = result_queue,
                    broker_seq: int = seq,
                    broker_key: str = bid,
                ) -> None:
                    observed_mono = 0.0
                    observed_epoch = 0.0
                    try:
                        value = target.get_account_balance()
                        scalar = _coerce_scalar(value)
                        if scalar is None:
                            raise ValueError("invalid_balance_payload")
                        observed_mono = time.monotonic()
                        observed_epoch = time.time()
                        with _OBSERVATION_LOCK:
                            previous = _OBSERVATIONS.get(broker_key)
                            if previous is None or broker_seq >= previous.sequence:
                                _OBSERVATIONS[broker_key] = _Observation(
                                    value=scalar,
                                    observed_monotonic=observed_mono,
                                    observed_epoch=observed_epoch,
                                    sequence=broker_seq,
                                )
                        try:
                            output.put_nowait(
                                (
                                    True,
                                    value,
                                    broker_seq,
                                    observed_mono,
                                    observed_epoch,
                                )
                            )
                        except queue.Full:
                            pass
                    except BaseException as exc:
                        try:
                            output.put_nowait(
                                (False, exc, broker_seq, observed_mono, observed_epoch)
                            )
                        except queue.Full:
                            pass
                    finally:
                        with _IN_FLIGHT_LOCK:
                            current = _IN_FLIGHT.get(broker_key)
                            if current is not None and current.sequence == broker_seq:
                                _IN_FLIGHT.pop(broker_key, None)

                thread = threading.Thread(
                    target=_call,
                    name=f"capital-balance-fetch-{bid}",
                    daemon=True,
                )
                flight = _Flight(
                    thread=thread,
                    result_queue=result_queue,
                    sequence=seq,
                    started_monotonic=started,
                    timeout_s=timeout_s,
                )
                _IN_FLIGHT[bid] = flight
                self._flights[bid] = flight
                thread.start()
                LOGGER.info(
                    "CAPITAL_REFRESH_FETCH_STARTED marker=%s latency_marker=%s broker=%s seq=%d timeout_s=%.1f cycle_remaining_s=%.1f",
                    MARKER,
                    LATENCY_MARKER,
                    bid,
                    seq,
                    timeout_s,
                    max(0.0, self._cycle_deadline - started),
                )

    def result_for(self, broker_id: str, broker: Any) -> Any:
        bid = str(broker_id).strip().lower()
        flight = self._flights[bid]
        broker_deadline = flight.started_monotonic + flight.timeout_s
        remaining = max(
            0.0,
            min(broker_deadline, self._cycle_deadline) - time.monotonic(),
        )
        try:
            ok, value, result_seq, observed_mono, observed_epoch = (
                flight.result_queue.get(timeout=remaining)
            )
        except queue.Empty:
            return self._handle_failure(bid, "timeout")

        if int(result_seq) != int(flight.sequence):
            LOGGER.warning(
                "CAPITAL_REFRESH_LATE_RESULT_DISCARDED marker=%s broker=%s result_seq=%s expected_seq=%s",
                MARKER,
                bid,
                result_seq,
                flight.sequence,
            )
            return self._handle_failure(bid, "late_result")
        if not ok:
            return self._handle_failure(bid, f"exception:{type(value).__name__}")
        scalar = _coerce_scalar(value)
        if scalar is None:
            return self._handle_failure(bid, "invalid_payload")

        live = dict(getattr(_REFRESH_CONTEXT, "live_brokers", {}) or {})
        live[bid] = {
            "value": scalar,
            "observed_monotonic": float(observed_mono),
            "observed_epoch": float(observed_epoch),
            "sequence": int(result_seq),
        }
        _REFRESH_CONTEXT.live_brokers = live
        if _WAS_TIMING_OUT.get(bid):
            _WAS_TIMING_OUT[bid] = False
            LOGGER.info(
                "CAPITAL_REFRESH_BROKER_RECOVERED marker=%s broker=%s live_data_restored=true",
                MARKER,
                bid,
            )
        return value

    def _handle_failure(self, broker_id: str, reason: str) -> float:
        _REFRESH_CONTEXT.used_fallback = True
        now = time.monotonic()
        ttl_s = _freshness_ttl_seconds()
        with _OBSERVATION_LOCK:
            observation = _OBSERVATIONS.get(broker_id)
        age_s = (
            max(0.0, now - observation.observed_monotonic)
            if observation is not None and observation.observed_monotonic > 0
            else float("inf")
        )
        fresh = bool(observation is not None and age_s <= ttl_s)
        last_logged = _LAST_TIMEOUT_LOGGED.get(broker_id, 0.0)
        suppress = (now - last_logged) < _TIMEOUT_LOG_DEDUP_S
        _WAS_TIMING_OUT[broker_id] = True

        if fresh and observation is not None:
            fallbacks = dict(
                getattr(_REFRESH_CONTEXT, "fallback_brokers", {}) or {}
            )
            fallbacks[broker_id] = {
                "value": observation.value,
                "age_s": age_s,
                "observed": True,
                "observed_epoch": observation.observed_epoch,
                "sequence": observation.sequence,
                "cached_valid": True,
                "reason": reason,
            }
            _REFRESH_CONTEXT.fallback_brokers = fallbacks
            if not suppress:
                _LAST_TIMEOUT_LOGGED[broker_id] = now
                LOGGER.warning(
                    "CAPITAL_REFRESH_BROKER_FETCH_TIMEOUT_FALLBACK marker=%s broker=%s reason=%s cached_payload=true cached_age_s=%.2f observed_epoch=%.6f source=cached_live_observation",
                    MARKER,
                    broker_id,
                    reason,
                    age_s,
                    observation.observed_epoch,
                )
            return float(observation.value)

        excluded = dict(getattr(_REFRESH_CONTEXT, "excluded_brokers", {}) or {})
        excluded[broker_id] = {
            "age_s": age_s,
            "observed": observation is not None,
            "observed_epoch": (
                observation.observed_epoch if observation is not None else 0.0
            ),
            "reason": reason,
            "cached_valid": False,
        }
        _REFRESH_CONTEXT.excluded_brokers = excluded
        if not suppress:
            _LAST_TIMEOUT_LOGGED[broker_id] = now
            LOGGER.error(
                "CAPITAL_REFRESH_BROKER_FETCH_TIMEOUT_EXCLUDED marker=%s broker=%s reason=%s cached_payload=false cached_age_s=%s action=exclude_from_snapshot",
                MARKER,
                broker_id,
                reason,
                "inf" if not math.isfinite(age_s) else f"{age_s:.2f}",
            )
        return 0.0


class _BoundedBrokerProxy:
    def __init__(self, broker_id: str, broker: Any, batch: _BalanceFetchBatch) -> None:
        object.__setattr__(self, "_broker_id", str(broker_id).strip().lower())
        object.__setattr__(self, "_broker", broker)
        object.__setattr__(self, "_batch", batch)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_broker"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_broker"), name, value)

    def get_account_balance(self) -> Any:
        return object.__getattribute__(self, "_batch").result_for(
            object.__getattribute__(self, "_broker_id"),
            object.__getattribute__(self, "_broker"),
        )


def _patch(module: ModuleType) -> bool:
    cls = getattr(module, "CapitalRefreshCoordinator", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_pipeline", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_capital_refresh_stall_guard_v36", False):
        return True

    @wraps(original)
    def _pipeline_with_bounded_brokers(
        self: Any,
        broker_map: Dict[str, Any],
        trigger: str,
        open_exposure_usd: float,
    ) -> Any:
        _begin_refresh_context()
        live_map = {
            str(broker_id).strip().lower(): broker
            for broker_id, broker in broker_map.items()
            if broker is not None
        }
        batch = _BalanceFetchBatch(live_map)
        bounded_map = {
            broker_id: _BoundedBrokerProxy(broker_id, broker, batch)
            for broker_id, broker in live_map.items()
        }
        try:
            return original(
                self,
                broker_map=bounded_map,
                trigger=trigger,
                open_exposure_usd=open_exposure_usd,
            )
        finally:
            status = _status_from_context()
            _REFRESH_CONTEXT.last_status = status
            _REFRESH_CONTEXT.in_refresh = False
            try:
                os.environ["NIJA_CAPITAL_REFRESH_LAST_PROVENANCE_JSON"] = str(status)
            except Exception:
                pass

    _pipeline_with_bounded_brokers._nija_capital_refresh_stall_guard_v35 = True  # type: ignore[attr-defined]
    _pipeline_with_bounded_brokers._nija_capital_refresh_stall_guard_v36 = True  # type: ignore[attr-defined]
    cls._pipeline = _pipeline_with_bounded_brokers
    os.environ["NIJA_CAPITAL_REFRESH_STALL_GUARD_V35_PATCHED"] = "1"
    os.environ["NIJA_CAPITAL_REFRESH_STALL_GUARD_V36_PATCHED"] = "1"
    os.environ["NIJA_CAPITAL_REFRESH_LIVE_LATENCY_V62_PATCHED"] = "1"
    LOGGER.critical(
        "CAPITAL_REFRESH_STALL_GUARD_V36_PATCHED marker=%s latency_marker=%s module=%s "
        "generic_timeout_s=%.1f coinbase_timeout_s=%.1f okx_timeout_s=%.1f kraken_timeout_s=%.1f "
        "cycle_deadline_coinbase_okx_s=%.1f queue_reuse=true stale_authority_fallback=false",
        MARKER,
        LATENCY_MARKER,
        module.__name__,
        _timeout_seconds(),
        _broker_timeout_seconds("coinbase"),
        _broker_timeout_seconds("okx"),
        _broker_timeout_seconds("kraken"),
        _cycle_deadline_seconds(("coinbase", "okx")),
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in _TARGETS:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch(module) or changed
    return changed


def install_import_hook() -> bool:
    global _STARTED
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(
                name: str,
                globals: Any = None,
                locals: Any = None,
                fromlist: Any = (),
                level: int = 0,
            ):
                module = original_import(name, globals, locals, fromlist, level)
                if str(name).endswith("capital_flow_state_machine"):
                    _patch_loaded()
                return module

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module(name: str, package: str | None = None):
                module = original_import_module(name, package)
                if str(name).endswith("capital_flow_state_machine"):
                    _patch_loaded()
                return module

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        _STARTED = True
        os.environ["NIJA_CAPITAL_REFRESH_STALL_GUARD_V35_INSTALLED"] = "1"
        os.environ["NIJA_CAPITAL_REFRESH_STALL_GUARD_V36_INSTALLED"] = "1"
        os.environ["NIJA_CAPITAL_REFRESH_LIVE_LATENCY_V62_INSTALLED"] = "1"
        LOGGER.critical(
            "CAPITAL_REFRESH_STALL_GUARD_V36_INSTALLED marker=%s latency_marker=%s safe_timeout_fallback=true broker_specific_deadlines=true",
            MARKER,
            LATENCY_MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "LATENCY_MARKER",
    "install",
    "install_import_hook",
    "current_refresh_used_fallback",
    "current_refresh_fallback_status",
    "_BalanceFetchBatch",
    "_BoundedBrokerProxy",
    "_broker_timeout_seconds",
    "_cycle_deadline_seconds",
    "_patch",
]
