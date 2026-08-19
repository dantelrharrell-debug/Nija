"""Runtime capital/position convergence repair v161.

Production on 2026-08-19 exposed two liveness defects that remained after the
v158 deadline-owner repair:

* a broker balance worker (most visibly Kraken) could outlive the synchronous
  capital publication budget and remain the reusable v35 in-flight request.
  Coordinator rollover therefore created a fresh coordinator while still
  inheriting the same stuck broker worker, allowing repeated partial 2/3
  CapitalAuthority snapshots and eventual 80-second runtime-pipeline rollover;
* platform position reconciliation retried only when the adopter returned
  normally. A bounded TimeoutError escaped the v108 retry loop, so canonical
  ``position_sync_ready`` could remain false even after the broker recovered.

v161 repairs those liveness paths without fabricating capital, positions, or
execution authority:

* seed the capital guard only from a broker-owned, timestamped balance that is
  still inside the canonical freshness TTL;
* supersede a v35 broker flight once it has consumed almost the entire v78
  synchronous fetch budget, with a strict cap on simultaneously orphaned daemon
  workers; v35 sequence checks keep older late results from overwriting newer
  observations;
* retry ordinary position-sync exceptions inside the existing bounded v108
  attempt loop instead of abandoning the worker after the first timeout;
* run a small periodic platform-position convergence tick independent of capital
  refresh. It only dispatches the existing authoritative adopter and republishes
  canonical readiness from observed broker state;
* attest this repair in the runtime release manifest.

The patch does not extend capital freshness/publication expiry, change risk
limits, clear kill switches, grant writer/nonce authority, force LIVE_ACTIVE, or
turn a failed broker read into success.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import sys
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_position_convergence_v161")
MARKER = "20260819-runtime-capital-position-convergence-v161"
RELEASE_ID = "20260819-runtime-convergence-v161"
_PATCH_ATTR = "_nija_runtime_capital_position_convergence_v161"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_POSITION_CONVERGENCE_V161_READY"
_LOCK = threading.RLock()
_INSTALLED = False
_POSITION_MONITOR_STARTED = False
_ORPHANED_FLIGHTS: dict[str, list[Any]] = {}


def _guard_module() -> ModuleType:
    return importlib.import_module("bot.capital_refresh_stall_guard_v35")


def _v108_module() -> ModuleType:
    return importlib.import_module("bot.platform_position_sync_v108_patch")


def _fetch_budget_seconds() -> float:
    try:
        v78 = importlib.import_module("bot.capital_refresh_live_continuity_v78_patch")
        getter = getattr(v78, "fetch_budget_seconds", None)
        if callable(getter):
            return max(5.0, float(getter()))
    except Exception:
        pass
    try:
        ttl = float(getattr(_guard_module(), "_freshness_ttl_seconds")())
    except Exception:
        ttl = 90.0
    return max(5.0, ttl - 30.0)


def _stale_flight_after_seconds(broker_id: str) -> float:
    guard = _guard_module()
    budget = _fetch_budget_seconds()
    try:
        broker_timeout = float(guard._broker_timeout_seconds(str(broker_id)))
    except Exception:
        broker_timeout = budget
    raw = str(os.environ.get("NIJA_CAPITAL_STALE_FLIGHT_AFTER_S", "") or "").strip()
    if raw:
        try:
            requested = float(raw)
        except (TypeError, ValueError):
            requested = budget - 5.0
    else:
        requested = budget - 5.0
    ceiling = max(2.0, min(broker_timeout, max(2.0, budget - 1.0)))
    return max(2.0, min(requested, ceiling))


def _max_orphaned_flights() -> int:
    try:
        value = int(float(os.environ.get("NIJA_CAPITAL_MAX_ORPHANED_FLIGHTS_PER_BROKER", "2") or 2))
    except (TypeError, ValueError):
        value = 2
    return max(1, min(value, 4))


def _wall_timestamp(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            result = value.timestamp()
        elif hasattr(value, "timestamp") and callable(value.timestamp):
            result = float(value.timestamp())
        else:
            result = float(value)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return result if math.isfinite(result) and result > 0.0 else None


def _seed_fresh_broker_observation(guard: ModuleType, broker_id: str, broker: Any) -> bool:
    """Seed v35 fallback state from a broker-owned, fresh timestamped balance."""
    bid = str(broker_id).strip().lower()
    if broker is None or not bool(getattr(broker, "connected", True)):
        return False

    raw = getattr(broker, "_last_known_balance", None)
    scalar_fn = getattr(guard, "_coerce_scalar", None)
    if not callable(scalar_fn):
        return False
    scalar = scalar_fn(raw)
    if scalar is None or float(scalar) <= 0.0:
        return False

    observed_epoch = _wall_timestamp(getattr(broker, "_balance_last_updated", None))
    getter = getattr(broker, "get_balance_fetch_timestamp", None)
    if observed_epoch is None and callable(getter):
        try:
            observed_epoch = _wall_timestamp(getter())
        except Exception:
            observed_epoch = None
    if observed_epoch is None:
        return False

    now_epoch = time.time()
    age_s = max(0.0, now_epoch - observed_epoch)
    try:
        ttl_s = float(guard._freshness_ttl_seconds())
    except Exception:
        ttl_s = 90.0
    if age_s > ttl_s:
        return False

    observed_mono = max(0.0, time.monotonic() - age_s)
    observations = getattr(guard, "_OBSERVATIONS", None)
    observation_cls = getattr(guard, "_Observation", None)
    lock = getattr(guard, "_OBSERVATION_LOCK", None)
    sequence_map = getattr(guard, "_BROKER_SEQUENCE", {})
    if not isinstance(observations, dict) or observation_cls is None:
        return False
    sequence = int(sequence_map.get(bid, 0) or 0)
    try:
        observation = observation_cls(
            value=float(scalar),
            observed_monotonic=observed_mono,
            observed_epoch=observed_epoch,
            sequence=sequence,
        )
    except TypeError:
        observation = observation_cls(float(scalar), observed_mono, observed_epoch, sequence)

    def _store() -> bool:
        previous = observations.get(bid)
        previous_mono = float(getattr(previous, "observed_monotonic", 0.0) or 0.0)
        if previous is None or observed_mono >= previous_mono:
            observations[bid] = observation
            return True
        return False

    stored = _store() if lock is None else False
    if lock is not None:
        with lock:
            stored = _store()
    if stored:
        LOGGER.info(
            "CAPITAL_V161_BROKER_CACHE_SEEDED marker=%s broker=%s balance=%.8f age_s=%.2f "
            "source=broker_timestamped_last_known freshness_extended=false",
            MARKER,
            bid,
            float(scalar),
            age_s,
        )
    return stored


def _prune_orphans(broker_id: str) -> list[Any]:
    bid = str(broker_id).strip().lower()
    alive: list[Any] = []
    for flight in list(_ORPHANED_FLIGHTS.get(bid, [])):
        thread = getattr(flight, "thread", None)
        is_alive = getattr(thread, "is_alive", None)
        if callable(is_alive) and bool(is_alive()):
            alive.append(flight)
    _ORPHANED_FLIGHTS[bid] = alive
    return alive


def _supersede_stale_guard_flights(guard: ModuleType, broker_map: dict[str, Any]) -> None:
    in_flight = getattr(guard, "_IN_FLIGHT", None)
    in_flight_lock = getattr(guard, "_IN_FLIGHT_LOCK", None)
    if not isinstance(in_flight, dict) or in_flight_lock is None:
        return
    now = time.monotonic()
    with in_flight_lock:
        for broker_id in broker_map:
            bid = str(broker_id).strip().lower()
            flight = in_flight.get(bid)
            if flight is None:
                continue
            thread = getattr(flight, "thread", None)
            is_alive = getattr(thread, "is_alive", None)
            if not callable(is_alive) or not bool(is_alive()):
                continue
            try:
                age_s = max(0.0, now - float(getattr(flight, "started_monotonic", now) or now))
            except (TypeError, ValueError):
                age_s = 0.0
            stale_after_s = _stale_flight_after_seconds(bid)
            if age_s < stale_after_s:
                continue
            orphans = _prune_orphans(bid)
            if len(orphans) >= _max_orphaned_flights():
                LOGGER.warning(
                    "CAPITAL_V161_STALE_FLIGHT_ROTATION_CAPPED marker=%s broker=%s age_s=%.2f "
                    "stale_after_s=%.2f live_orphans=%d max_orphans=%d current_reused=true",
                    MARKER,
                    bid,
                    age_s,
                    stale_after_s,
                    len(orphans),
                    _max_orphaned_flights(),
                )
                continue
            if in_flight.get(bid) is not flight:
                continue
            in_flight.pop(bid, None)
            orphans.append(flight)
            _ORPHANED_FLIGHTS[bid] = orphans
            LOGGER.critical(
                "CAPITAL_V161_STALE_FLIGHT_SUPERSEDED marker=%s broker=%s sequence=%s age_s=%.2f "
                "stale_after_s=%.2f live_orphans=%d late_result_sequence_guard=true "
                "new_fetch_allowed=true freshness_extended=false",
                MARKER,
                bid,
                getattr(flight, "sequence", "unknown"),
                age_s,
                stale_after_s,
                len(orphans),
            )


def _patch_capital_batch() -> bool:
    guard = _guard_module()
    batch_cls = getattr(guard, "_BalanceFetchBatch", None)
    if not isinstance(batch_cls, type):
        return False
    current = getattr(batch_cls, "__init__", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def init_v161(self: Any, broker_map: dict[str, Any]) -> None:
        live_map = {
            str(broker_id).strip().lower(): broker
            for broker_id, broker in dict(broker_map or {}).items()
            if broker is not None
        }
        for bid, broker in live_map.items():
            try:
                _seed_fresh_broker_observation(guard, bid, broker)
            except Exception as exc:
                LOGGER.debug(
                    "CAPITAL_V161_CACHE_SEED_ERROR marker=%s broker=%s error=%s:%s",
                    MARKER,
                    bid,
                    type(exc).__name__,
                    exc,
                )
        _supersede_stale_guard_flights(guard, live_map)
        original(self, broker_map)

    setattr(init_v161, _PATCH_ATTR, True)
    setattr(init_v161, "__wrapped__", original)
    batch_cls.__init__ = init_v161
    return True


def _startup_sync_module() -> ModuleType:
    try:
        return importlib.import_module("bot.startup_position_sync")
    except ImportError:
        return importlib.import_module("startup_position_sync")


def _position_worker_v161(
    v108: ModuleType,
    manager: Any,
    broker_name: str,
    broker: Any,
    key: tuple[int, int],
    trigger: str,
) -> None:
    try:
        sync_module = _startup_sync_module()
        get_eps = getattr(sync_module, "_get_entry_price_store", None)
        eps = get_eps() if callable(get_eps) else None
        adopt = getattr(sync_module, "_adopt_broker_positions", None)
        if not callable(adopt):
            raise RuntimeError("startup position-sync adopter unavailable")

        max_attempts, base_delay_s, max_delay_s = v108._retry_policy()
        LOGGER.critical(
            "POSITION_SYNC_V161_START marker=%s broker=%s trigger=%s authoritative_fetch=true "
            "exception_retry=true max_attempts=%d synthetic_empty_snapshot=false",
            MARKER,
            broker_name,
            trigger,
            max_attempts,
        )
        for attempt in range(1, max_attempts + 1):
            attempt_error: BaseException | None = None
            try:
                adopt(broker, f"platform:{broker_name}", eps)
            except Exception as exc:
                attempt_error = exc
                setattr(broker, "_startup_position_sync_adopted", False)
                setattr(broker, "_startup_position_sync_fetch_ok", False)
                setattr(broker, "_startup_position_sync_error", f"{type(exc).__name__}:{exc}")
                LOGGER.warning(
                    "POSITION_SYNC_V161_ATTEMPT_FAILED marker=%s broker=%s trigger=%s attempt=%d "
                    "error=%s:%s retryable=true trading_fail_closed=true",
                    MARKER,
                    broker_name,
                    trigger,
                    attempt,
                    type(exc).__name__,
                    exc,
                )

            synced = bool(getattr(broker, "_startup_position_sync_adopted", False))
            fetch_ok = getattr(broker, "_startup_position_sync_fetch_ok", None)
            error = getattr(broker, "_startup_position_sync_error", None)
            v108._publish_readiness(
                manager,
                source=f"v161:{trigger}:{broker_name}:attempt_{attempt}",
            )
            if synced:
                LOGGER.critical(
                    "POSITION_SYNC_V161_COMPLETE marker=%s broker=%s trigger=%s attempt=%d "
                    "synced=true fetch_ok=%s error=%s",
                    MARKER,
                    broker_name,
                    trigger,
                    attempt,
                    fetch_ok,
                    error,
                )
                break

            if attempt >= max_attempts:
                LOGGER.warning(
                    "POSITION_SYNC_V161_RETRIES_EXHAUSTED marker=%s broker=%s trigger=%s attempts=%d "
                    "synced=false fetch_ok=%s error=%s last_attempt_exception=%s trading_fail_closed=true",
                    MARKER,
                    broker_name,
                    trigger,
                    max_attempts,
                    fetch_ok,
                    error,
                    type(attempt_error).__name__ if attempt_error is not None else "none",
                )
                break

            delay_s = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
            LOGGER.warning(
                "POSITION_SYNC_V161_RETRY marker=%s broker=%s trigger=%s attempt=%d next_attempt=%d "
                "delay_s=%.2f synced=false fetch_ok=%s error=%s trading_fail_closed=true",
                MARKER,
                broker_name,
                trigger,
                attempt,
                attempt + 1,
                delay_s,
                fetch_ok,
                error,
            )
            time.sleep(delay_s)
    except BaseException as exc:
        try:
            setattr(broker, "_startup_position_sync_adopted", False)
            setattr(broker, "_startup_position_sync_fetch_ok", False)
            setattr(broker, "_startup_position_sync_error", f"{type(exc).__name__}:{exc}")
        except Exception:
            pass
        LOGGER.warning(
            "POSITION_SYNC_V161_FAILED marker=%s broker=%s trigger=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            broker_name,
            trigger,
            type(exc).__name__,
            exc,
        )
    finally:
        try:
            v108._publish_readiness(manager, source=f"v161:{trigger}:{broker_name}:final")
        except Exception:
            pass
        lock = getattr(v108, "_LOCK", None)
        active = getattr(v108, "_ACTIVE", None)
        if lock is not None and isinstance(active, set):
            with lock:
                active.discard(key)


def _patch_position_worker() -> bool:
    v108 = _v108_module()
    current = getattr(v108, "_worker", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def worker_v161(manager: Any, broker_name: str, broker: Any, key: tuple[int, int], trigger: str) -> None:
        _position_worker_v161(v108, manager, broker_name, broker, key, trigger)

    setattr(worker_v161, _PATCH_ATTR, True)
    setattr(worker_v161, "__wrapped__", current)
    v108._worker = worker_v161
    return True


def _canonical_manager() -> Any:
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        getter = getattr(module, "get_broker_manager", None)
        if callable(getter):
            try:
                manager = getter()
                if manager is not None:
                    return manager
            except Exception:
                pass
        manager = getattr(module, "multi_account_broker_manager", None) or getattr(module, "_manager", None)
        if manager is not None:
            return manager
    return None


def _position_monitor_interval_seconds() -> float:
    try:
        value = float(os.environ.get("NIJA_POSITION_SYNC_CONVERGENCE_INTERVAL_S", "5.0") or 5.0)
    except (TypeError, ValueError):
        value = 5.0
    return max(1.0, min(value, 30.0))


def _position_monitor_iteration() -> tuple[int, bool]:
    manager = _canonical_manager()
    if manager is None:
        return 0, False
    v108 = _v108_module()
    started = int(v108.dispatch_platform_position_sync(manager, trigger="v161_monitor") or 0)
    try:
        v108._publish_readiness(manager, source="v161_monitor_tick")
        published = True
    except Exception as exc:
        LOGGER.warning(
            "POSITION_SYNC_V161_MONITOR_PUBLISH_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        published = False
    return started, published


def _position_monitor() -> None:
    while True:
        try:
            started, published = _position_monitor_iteration()
            LOGGER.debug(
                "POSITION_SYNC_V161_MONITOR_TICK marker=%s workers_started=%d readiness_published=%s",
                MARKER,
                started,
                str(published).lower(),
            )
        except Exception as exc:
            LOGGER.warning(
                "POSITION_SYNC_V161_MONITOR_ERROR marker=%s error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(_position_monitor_interval_seconds())


def _start_position_monitor() -> bool:
    global _POSITION_MONITOR_STARTED
    with _LOCK:
        if _POSITION_MONITOR_STARTED:
            return True
        thread = threading.Thread(
            target=_position_monitor,
            name="RuntimeCapitalPositionConvergenceV161",
            daemon=True,
        )
        thread.start()
        _POSITION_MONITOR_STARTED = True
        LOGGER.critical(
            "POSITION_SYNC_V161_MONITOR_STARTED marker=%s interval_s=%.1f "
            "capital_refresh_dependency=false authoritative_adopter_only=true",
            MARKER,
            _position_monitor_interval_seconds(),
        )
        return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    except Exception:
        return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["runtime_capital_position_convergence_v161"] = _READY_FLAG
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        capital_ok = _patch_capital_batch()
        position_ok = _patch_position_worker()
        manifest_ok = _patch_release_manifest()
        if not (capital_ok and position_ok and manifest_ok):
            os.environ[_READY_FLAG] = "0"
            LOGGER.critical(
                "RUNTIME_CAPITAL_POSITION_CONVERGENCE_V161_FAILED marker=%s capital_ok=%s "
                "position_ok=%s manifest_ok=%s trading_fail_closed=true",
                MARKER,
                capital_ok,
                position_ok,
                manifest_ok,
            )
            return False
        _start_position_monitor()
        os.environ[_READY_FLAG] = "1"
        _INSTALLED = True
        LOGGER.critical(
            "RUNTIME_CAPITAL_POSITION_CONVERGENCE_V161 marker=%s ready=true "
            "capital_stale_after_s=%.1f fetch_budget_s=%.1f max_orphans=%d "
            "position_exception_retry=true position_monitor=true freshness_extended=false "
            "publication_expiry_extended=false safety_gates_bypassed=false",
            MARKER,
            _stale_flight_after_seconds("kraken"),
            _fetch_budget_seconds(),
            _max_orphaned_flights(),
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_patch_capital_batch",
    "_patch_position_worker",
    "_position_worker_v161",
    "_position_monitor_iteration",
    "_seed_fresh_broker_observation",
    "_stale_flight_after_seconds",
]
