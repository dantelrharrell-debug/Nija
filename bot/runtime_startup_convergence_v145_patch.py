"""NIJA runtime startup convergence v145.

Closes the production startup/liveness gaps observed after v144 deployment:

* an alive but already-expired capital balance worker must never be reused by a
  later refresh cycle;
* superseded workers are sequence-fenced so a late return cannot become a fresh
  capital observation;
* expected repeated activation deferrals are coalesced without changing their
  fail-closed decision; and
* v145 becomes the terminal release owner while preserving all v144 entry and
  AI safety gates.

No balance is fabricated, no freshness TTL is extended, no broker timeout is
relaxed, and no activation/entry gate is bypassed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_startup_convergence_v145")
MARKER = "20260818-runtime-startup-convergence-v145"
RELEASE_ID = "20260818-runtime-convergence-v145"
_FLAG = "NIJA_RUNTIME_STARTUP_CONVERGENCE_V145_READY"
_PATCH_ATTR = "_nija_runtime_startup_convergence_v145"
_LOCK = threading.RLock()
_INSTALLED = False
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _expired_alive_flight(flight: Any, now: float | None = None) -> bool:
    """Return True only for a live worker whose own hard deadline has elapsed."""
    if flight is None:
        return False
    thread = getattr(flight, "thread", None)
    if thread is None or not callable(getattr(thread, "is_alive", None)):
        return False
    try:
        alive = bool(thread.is_alive())
    except Exception:
        return False
    if not alive:
        return False
    try:
        started = float(getattr(flight, "started_monotonic", 0.0) or 0.0)
        timeout_s = max(0.0, float(getattr(flight, "timeout_s", 0.0) or 0.0))
    except Exception:
        return False
    current = time.monotonic() if now is None else float(now)
    return bool(started > 0.0 and timeout_s > 0.0 and current >= started + timeout_s)


def _fence_expired_flight(guard: ModuleType, broker_id: str, now: float | None = None) -> bool:
    """Evict and sequence-fence an expired worker without cancelling its thread.

    Python cannot safely terminate a blocking network thread. Instead, the old
    worker is removed from the reusable in-flight registry and a non-usable
    sequence fence is installed in the observation table. If the old worker
    later returns, its lower sequence cannot overwrite the fence. A new batch
    then starts a fresh worker with a strictly newer sequence.
    """
    bid = str(broker_id or "").strip().lower()
    if not bid:
        return False

    inflight = getattr(guard, "_IN_FLIGHT", None)
    inflight_lock = getattr(guard, "_IN_FLIGHT_LOCK", None)
    sequences = getattr(guard, "_BROKER_SEQUENCE", None)
    observations = getattr(guard, "_OBSERVATIONS", None)
    observation_lock = getattr(guard, "_OBSERVATION_LOCK", None)
    observation_cls = getattr(guard, "_Observation", None)
    if not isinstance(inflight, dict) or not isinstance(sequences, dict):
        return False
    if not isinstance(observations, dict) or observation_cls is None:
        return False
    if inflight_lock is None or observation_lock is None:
        return False

    current = time.monotonic() if now is None else float(now)
    # Observation -> in-flight lock ordering is safe here: the worker publishes
    # an observation and releases that lock before entering its final in-flight
    # cleanup, so it never holds the reverse pair simultaneously.
    with observation_lock:
        with inflight_lock:
            existing = inflight.get(bid)
            if not _expired_alive_flight(existing, current):
                return False

            old_seq = int(getattr(existing, "sequence", 0) or 0)
            age_s = max(
                0.0,
                current - float(getattr(existing, "started_monotonic", current) or current),
            )
            timeout_s = max(0.0, float(getattr(existing, "timeout_s", 0.0) or 0.0))
            inflight.pop(bid, None)

            # Reserve a sequence strictly newer than the expired worker. The
            # original batch constructor will increment again for the new flight.
            fence_seq = max(int(sequences.get(bid, 0) or 0), old_seq) + 1
            sequences[bid] = fence_seq

            previous = observations.get(bid)
            if previous is not None:
                value = float(getattr(previous, "value", 0.0) or 0.0)
                observed_mono = float(getattr(previous, "observed_monotonic", 0.0) or 0.0)
                observed_epoch = float(getattr(previous, "observed_epoch", 0.0) or 0.0)
            else:
                # Zero with zero timestamps is intentionally unusable as a
                # freshness fallback; it exists only as a sequence fence.
                value = 0.0
                observed_mono = 0.0
                observed_epoch = 0.0
            try:
                observations[bid] = observation_cls(
                    value=value,
                    observed_monotonic=observed_mono,
                    observed_epoch=observed_epoch,
                    sequence=fence_seq,
                )
            except TypeError:
                observations[bid] = observation_cls(
                    value,
                    observed_mono,
                    observed_epoch,
                    fence_seq,
                )

    LOGGER.warning(
        "CAPITAL_REFRESH_EXPIRED_INFLIGHT_SUPERSEDED marker=%s broker=%s old_seq=%d fence_seq=%d age_s=%.3f timeout_s=%.3f late_result_fenced=true new_worker_required=true",
        MARKER,
        bid,
        old_seq,
        fence_seq,
        age_s,
        timeout_s,
    )
    return True


def _patch_capital_guard(guard: ModuleType) -> bool:
    batch_cls = getattr(guard, "_BalanceFetchBatch", None)
    current = getattr(batch_cls, "__init__", None) if isinstance(batch_cls, type) else None
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def init_v145(self: Any, broker_map: dict[str, Any]) -> None:
        now = time.monotonic()
        for broker_id in tuple((broker_map or {}).keys()):
            try:
                _fence_expired_flight(guard, str(broker_id), now)
            except Exception as exc:
                # Failure to fence must not silently permit stale reuse. Remove
                # only an expired registry entry; the old daemon may finish but
                # result_for will not be handed that object by a new batch.
                LOGGER.exception(
                    "CAPITAL_REFRESH_EXPIRED_INFLIGHT_FENCE_ERROR marker=%s broker=%s error=%s",
                    MARKER,
                    broker_id,
                    exc,
                )
                raise
        current(self, broker_map)

    setattr(init_v145, _PATCH_ATTR, True)
    setattr(init_v145, "__wrapped__", current)
    batch_cls.__init__ = init_v145
    return True


def _patch_activation_deferral(module: ModuleType) -> bool:
    current = getattr(module, "_log_activation_deferred", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    state = {"signature": "", "ts": 0.0, "suppressed": 0}
    gate = threading.Lock()

    @wraps(current)
    def log_deferred_v145(trigger: str, blockers: list[str], details: dict[str, Any]) -> None:
        signature = "|".join(
            (
                str(trigger or ""),
                ",".join(str(v) for v in blockers),
                str(details.get("generation", 0)),
                str(details.get("bootstrap_state", "")),
                str(details.get("core_registered", False)),
                str(details.get("core_alive", False)),
            )
        )
        now = time.monotonic()
        try:
            interval = max(
                1.0,
                float(os.environ.get("NIJA_ACTIVATION_DEFER_LOG_INTERVAL_S", "15") or 15.0),
            )
        except Exception:
            interval = 15.0
        with gate:
            if signature == state["signature"] and now - float(state["ts"]) < interval:
                state["suppressed"] = int(state["suppressed"]) + 1
                logging.getLogger("nija.final_production_activation_repair_v61").debug(
                    "ACTIVATION_SINGLE_FLIGHT_DEFERRED_COALESCED marker=%s trigger=%s blockers=%s suppressed=%d trading_fail_closed=true",
                    MARKER,
                    trigger,
                    blockers,
                    state["suppressed"],
                )
                return
            suppressed = int(state["suppressed"])
            state["signature"] = signature
            state["ts"] = now
            state["suppressed"] = 0
        current(trigger, blockers, details)
        if suppressed:
            logging.getLogger("nija.final_production_activation_repair_v61").info(
                "ACTIVATION_DEFER_REPEAT_SUMMARY marker=%s trigger=%s suppressed=%d",
                MARKER,
                trigger,
                suppressed,
            )

    setattr(log_deferred_v145, _PATCH_ATTR, True)
    setattr(log_deferred_v145, "__wrapped__", current)
    module._log_activation_deferred = log_deferred_v145
    return True


def _own_release() -> bool:
    manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["runtime_startup_convergence_v145"] = _FLAG
    manifest.DECLARED_RELEASE_ID = RELEASE_ID
    manifest.RELEASE_ID = RELEASE_ID
    os.environ["NIJA_RUNTIME_RELEASE_ID"] = RELEASE_ID

    # v144's monitor is intentionally retained; update its terminal identity so
    # any later reassertion preserves, rather than downgrades, the v145 release.
    try:
        v144 = importlib.import_module("bot.runtime_quality_hardening_v144_patch")
        v144.RELEASE_ID = RELEASE_ID
    except Exception:
        return False
    return True


def _patch_loaded() -> dict[str, bool]:
    results: dict[str, bool] = {}
    try:
        guard = importlib.import_module("bot.capital_refresh_stall_guard_v35")
        results["capital_expired_flight_fence"] = _patch_capital_guard(guard)
    except Exception:
        results["capital_expired_flight_fence"] = False
        LOGGER.exception("RUNTIME_STARTUP_V145_CAPITAL_PATCH_FAILED marker=%s", MARKER)

    try:
        activation = importlib.import_module("bot.final_production_activation_repair_v61_patch")
        results["activation_defer_coalescing"] = _patch_activation_deferral(activation)
    except Exception:
        # Telemetry coalescing is not authority-critical.
        results["activation_defer_coalescing"] = False
        LOGGER.debug("RUNTIME_STARTUP_V145_ACTIVATION_LOG_PATCH_PENDING marker=%s", MARKER, exc_info=True)

    try:
        results["release_owner"] = _own_release()
    except Exception:
        results["release_owner"] = False
        LOGGER.exception("RUNTIME_STARTUP_V145_RELEASE_OWNER_FAILED marker=%s", MARKER)
    return results


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        results = _patch_loaded()
        # The capital fence and release ownership are safety/liveness critical.
        ready = bool(results.get("capital_expired_flight_fence") and results.get("release_owner"))
        if ready:
            os.environ[_FLAG] = "1"
            _INSTALLED = True
            LOGGER.info(
                "RUNTIME_STARTUP_CONVERGENCE_V145_INSTALLED marker=%s release=%s results=%s stale_flight_reuse=false late_result_fenced=true activation_gates_unchanged=true",
                MARKER,
                RELEASE_ID,
                results,
            )
            return True
        os.environ[_FLAG] = "0"
        LOGGER.critical(
            "RUNTIME_STARTUP_CONVERGENCE_V145_FAILED marker=%s results=%s trading_fail_closed=true",
            MARKER,
            results,
        )
        return False


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_expired_alive_flight",
    "_fence_expired_flight",
    "_patch_capital_guard",
    "_patch_activation_deferral",
    "_own_release",
]
