"""Single-owner writer lease convergence v82.

This patch removes the last authority split observed in production after v80/v81.
Only EntrypointWriterAuthority may acquire or renew the Redis writer lock.
AuthorityHeartbeatMonitor becomes an observer/telemetry process and may never
recreate a missing lock, extend its TTL, or copy a Redis generation into local
writer state.

It also closes the acquisition publication race: a fresh writer result is fully
published before its epoch-bound lease heartbeat is started. Every lease-heartbeat
thread captures the generation it belongs to and exits if a newer generation is
installed, so a stale worker cannot act on the next writer epoch.

The v39 recovery monitor is recreated as a fresh AuthorityHeartbeatMonitor only
after the old monitor has stopped, preventing an old monitor from carrying
failure counters or stop state across a successful re-election.

Safety invariants
-----------------
* no blind Redis-generation adoption;
* no secondary lock creation/TTL extension;
* exact writer singleton ownership is required for observer heartbeat success;
* stale epoch threads exit instead of mutating a newer epoch;
* all execution/risk/capital/broker gates remain fail-closed.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.writer_single_owner_convergence_v82")
MARKER = "20260809-writer-single-owner-convergence-v82"
_LOCK = threading.RLock()
_PATCH_ATTR = "_nija_writer_single_owner_v82"


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled", "y"}


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _entrypoint_runtime() -> Any:
    for name in ("bot.entrypoint_writer_authority", "entrypoint_writer_authority"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        getter = getattr(module, "get_entrypoint_writer_authority", None)
        if callable(getter):
            try:
                runtime = getter()
            except Exception:
                continue
            if runtime is not None:
                return runtime
    return None


def _exact_runtime_owner(runtime: Any = None) -> tuple[bool, str, int]:
    runtime = runtime or _entrypoint_runtime()
    if runtime is None:
        return False, "runtime_unavailable", 0
    if not bool(getattr(runtime, "acquired", False)) or bool(getattr(runtime, "lost", True)):
        return False, "runtime_not_acquired", _as_int(getattr(runtime, "_generation", 0))
    if bool(getattr(runtime, "_local_fallback", False)):
        return False, "local_fallback_not_distributed", _as_int(getattr(runtime, "_generation", 0))

    client = getattr(runtime, "_client", None)
    lock_key = str(getattr(runtime, "_lock_key", "") or "").strip()
    lock_value = str(getattr(runtime, "_lock_value", "") or "").strip()
    generation = _as_int(getattr(runtime, "_generation", 0))
    generation_key = str(os.environ.get("NIJA_LEASE_GENERATION_KEY", "") or "nija:lease:generation").strip()
    if client is None or not lock_key or not lock_value or generation <= 0:
        return False, "runtime_identity_incomplete", generation
    try:
        current = _as_text(client.get(lock_key)).strip()
        redis_generation = _as_int(client.get(generation_key), 0)
        pttl = _as_int(client.pttl(lock_key), -2)
    except Exception as exc:
        return False, f"redis_owner_probe_failed:{type(exc).__name__}:{exc}", generation
    if current != lock_value:
        return False, "lock_missing" if not current else "lock_owned_by_other", generation
    if redis_generation != generation:
        return False, f"generation_mismatch:{generation}!={redis_generation}", generation
    if pttl <= 0:
        return False, f"lock_ttl_not_positive:{pttl}", generation
    return True, "exact_owner", generation


def _patch_entrypoint_authority() -> bool:
    try:
        module = importlib.import_module("bot.entrypoint_writer_authority")
    except Exception:
        return False
    cls = getattr(module, "EntrypointWriterAuthority", None)
    writer_state = getattr(module, "WriterState", None)
    cfg_float = getattr(module, "_cfg_float", None)
    heartbeat_state_getter = getattr(module, "_get_heartbeat_state", None)
    if not isinstance(cls, type) or writer_state is None:
        return False

    original_start = getattr(cls, "_start_heartbeat", None)
    original_activate = getattr(cls, "_activate_distributed_authority", None)
    if not callable(original_start) or not callable(original_activate):
        return False

    if not getattr(original_start, _PATCH_ATTR, False):
        def start_heartbeat_v82(self: Any) -> None:
            if bool(getattr(self, "_nija_v82_activation_in_progress", False)):
                return
            if bool(getattr(self, "_local_fallback", False)):
                return
            generation = _as_int(getattr(self, "_generation", 0))
            if generation <= 0 or not bool(getattr(self, "acquired", False)):
                LOGGER.warning(
                    "WRITER_V82_HEARTBEAT_START_BLOCKED marker=%s generation=%s acquired=%s",
                    MARKER,
                    generation,
                    bool(getattr(self, "acquired", False)),
                )
                return
            current = getattr(self, "_heartbeat_thread", None)
            if current is not None and callable(getattr(current, "is_alive", None)) and current.is_alive():
                current_epoch = _as_int(getattr(current, "_nija_writer_epoch_generation", 0))
                if current_epoch == generation:
                    return

            interval_s = 5.0
            if callable(cfg_float):
                try:
                    interval_s = cfg_float(
                        "NIJA_WRITER_HEARTBEAT_INTERVAL_S",
                        min(5.0, max(1.0, float(getattr(self, "_ttl_s", 60)) / 3.0)),
                        minimum=1.0,
                    )
                except Exception:
                    interval_s = 5.0
            grace_s = float(getattr(self, "_resolve_loss_grace_s", lambda: 12.0)())

            def epoch_loop() -> None:
                failures = 0
                first_failure_at = 0.0
                while not getattr(self, "_stop").is_set():
                    if _as_int(getattr(self, "_generation", 0)) != generation:
                        LOGGER.info(
                            "WRITER_V82_STALE_EPOCH_HEARTBEAT_EXIT marker=%s thread_generation=%s current_generation=%s",
                            MARKER,
                            generation,
                            getattr(self, "_generation", 0),
                        )
                        return
                    if not bool(getattr(self, "acquired", False)) or bool(getattr(self, "lost", True)):
                        return
                    ok, reason = self._heartbeat_tick()
                    if _as_int(getattr(self, "_generation", 0)) != generation:
                        return
                    if ok:
                        failures = 0
                        first_failure_at = 0.0
                        self._set_writer_state(writer_state.ACTIVE, reason="heartbeat_ok_v82")
                    else:
                        if callable(heartbeat_state_getter):
                            try:
                                heartbeat_state_getter().record_heartbeat_failure()
                            except Exception:
                                pass
                        failures += 1
                        now = time.time()
                        if first_failure_at <= 0.0:
                            first_failure_at = now
                        elapsed = max(0.0, now - first_failure_at)
                        ownership_lost = reason in {
                            "lock_owned_by_different_writer",
                            "lock_missing_and_fencing_token_mismatch",
                        }
                        if ownership_lost:
                            self._set_writer_state(writer_state.LOST, reason=f"ownership_lost:{reason}")
                            self._mark_lost(reason)
                            return
                        self._set_writer_state(writer_state.REFRESHING, reason=f"heartbeat_failure:{reason}")
                        if elapsed >= grace_s:
                            self._set_writer_state(writer_state.LOST, reason=f"heartbeat_grace_expired:{reason}")
                            self._mark_lost(f"heartbeat_grace_expired:{reason}")
                            return
                    if getattr(self, "_stop").wait(interval_s):
                        return

            thread = threading.Thread(
                target=epoch_loop,
                name=f"entrypoint-writer-lock-heartbeat-g{generation}",
                daemon=True,
            )
            setattr(thread, "_nija_writer_epoch_generation", generation)
            self._heartbeat_thread = thread
            thread.start()
            LOGGER.critical(
                "WRITER_V82_EPOCH_HEARTBEAT_STARTED marker=%s generation=%s thread=%s",
                MARKER,
                generation,
                thread.name,
            )

        setattr(start_heartbeat_v82, _PATCH_ATTR, True)
        setattr(start_heartbeat_v82, "__wrapped__", original_start)
        cls._start_heartbeat = start_heartbeat_v82

    current_activate = getattr(cls, "_activate_distributed_authority", None)
    if callable(current_activate) and not getattr(current_activate, _PATCH_ATTR, False):
        @wraps(current_activate)
        def activate_v82(self: Any, *args: Any, **kwargs: Any):
            self._nija_v82_activation_in_progress = True
            try:
                result = current_activate(self, *args, **kwargs)
            finally:
                self._nija_v82_activation_in_progress = False
            # current_activate has now assigned self._result, published all env
            # lineage, and cleared the lost state. Only now may the epoch
            # keepalive start.
            if bool(getattr(result, "acquired", False)):
                self._start_heartbeat()
                LOGGER.critical(
                    "WRITER_V82_ACQUISITION_COMMITTED marker=%s generation=%s result_published=%s heartbeat_after_commit=true",
                    MARKER,
                    getattr(result, "generation", 0),
                    bool(getattr(self, "_result", None) is result),
                )
            return result

        setattr(activate_v82, _PATCH_ATTR, True)
        setattr(activate_v82, "__wrapped__", current_activate)
        cls._activate_distributed_authority = activate_v82

    os.environ["NIJA_WRITER_SINGLE_OWNER_ENTRYPOINT_V82"] = "1"
    return True


def _patch_authority_observer() -> bool:
    try:
        module = importlib.import_module("bot.authority_heartbeat")
    except Exception:
        return False
    current_check = getattr(module, "_check_authority_once", None)
    monitor_cls = getattr(module, "AuthorityHeartbeatMonitor", None)
    if not callable(current_check) or not isinstance(monitor_cls, type):
        return False

    if not getattr(current_check, _PATCH_ATTR, False):
        @wraps(current_check)
        def check_v82(timeout_s: float):
            token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
            generation = _as_int(
                os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")
                or os.environ.get("NIJA_WRITER_GENERATION", ""),
                0,
            )
            # Once writer lineage exists, the in-process canonical runtime must
            # prove the exact same Redis owner. Never degrade this to ping-only.
            if token or generation > 0 or _truthy(os.environ.get("NIJA_WRITER_LEASE_ACQUIRED")):
                ok, reason, _ = _exact_runtime_owner()
                if not ok:
                    return False, f"writer_runtime_owner_unproven:{reason}"
            return current_check(timeout_s)

        setattr(check_v82, _PATCH_ATTR, True)
        setattr(check_v82, "__wrapped__", current_check)
        module._check_authority_once = check_v82

    current_write = getattr(monitor_cls, "_write_heartbeat_to_redis", None)
    if callable(current_write) and not getattr(current_write, _PATCH_ATTR, False):
        def observer_write_v82(self: Any) -> None:
            ok, reason, generation = _exact_runtime_owner()
            if not ok:
                LOGGER.warning(
                    "WRITER_V82_OBSERVER_WRITE_SKIPPED marker=%s reason=%s generation=%s lock_mutation=false generation_mutation=false",
                    MARKER,
                    reason,
                    generation,
                )
                return
            runtime = _entrypoint_runtime()
            client = getattr(runtime, "_client", None) if runtime is not None else None
            if client is None:
                return
            payload = {
                "timestamp": time.time(),
                "generation": generation,
                "instance_id": str(os.environ.get("NIJA_WRITER_INSTANCE_ID", "") or "unknown"),
                "source": "authority_heartbeat_observer_v82",
            }
            try:
                # Auxiliary telemetry key only. This is deliberately not the
                # writer lock, fencing counter, generation key or lock metadata.
                client.set("nija:writer_heartbeat_active", json.dumps(payload), ex=30)
                LOGGER.debug(
                    "WRITER_V82_OBSERVER_HEARTBEAT_WRITTEN marker=%s generation=%s lock_mutation=false",
                    MARKER,
                    generation,
                )
            except Exception as exc:
                LOGGER.warning(
                    "WRITER_V82_OBSERVER_HEARTBEAT_FAILED marker=%s error=%s:%s",
                    MARKER,
                    type(exc).__name__,
                    exc,
                )

        setattr(observer_write_v82, _PATCH_ATTR, True)
        setattr(observer_write_v82, "__wrapped__", current_write)
        monitor_cls._write_heartbeat_to_redis = observer_write_v82

    os.environ["NIJA_AUTHORITY_HEARTBEAT_OBSERVER_ONLY_V82"] = "1"
    return True


def _patch_v39_monitor_restart() -> bool:
    try:
        module = importlib.import_module("bot.production_readiness_v39_patch")
        heartbeat_module = importlib.import_module("bot.authority_heartbeat")
    except Exception:
        return False
    current = getattr(module, "_restart_authority_monitor", None)
    monitor_cls = getattr(heartbeat_module, "AuthorityHeartbeatMonitor", None)
    if not callable(current) or not isinstance(monitor_cls, type):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    def restart_monitor_v82(bot_main_module: ModuleType) -> bool:
        old = getattr(bot_main_module, "_authority_heartbeat_monitor", None)
        if old is not None:
            stop = getattr(old, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
            thread = getattr(old, "_thread", None)
            if thread is not None and callable(getattr(thread, "join", None)) and thread is not threading.current_thread():
                try:
                    thread.join(timeout=6.0)
                except Exception:
                    pass
                if callable(getattr(thread, "is_alive", None)) and thread.is_alive():
                    LOGGER.error(
                        "WRITER_V82_OLD_AUTHORITY_MONITOR_STILL_ALIVE marker=%s action=fail_closed",
                        MARKER,
                    )
                    return False

        ok, reason, generation = _exact_runtime_owner()
        if not ok:
            LOGGER.error(
                "WRITER_V82_MONITOR_RESTART_BLOCKED marker=%s reason=%s generation=%s",
                MARKER,
                reason,
                generation,
            )
            return False
        monitor = monitor_cls()
        monitor.start()
        setattr(bot_main_module, "_authority_heartbeat_monitor", monitor)
        thread = getattr(monitor, "_thread", None)
        healthy = bool(thread is not None and callable(getattr(thread, "is_alive", None)) and thread.is_alive())
        LOGGER.critical(
            "WRITER_V82_AUTHORITY_MONITOR_RECREATED marker=%s generation=%s healthy=%s fresh_instance=true",
            MARKER,
            generation,
            str(healthy).lower(),
        )
        return healthy

    setattr(restart_monitor_v82, _PATCH_ATTR, True)
    setattr(restart_monitor_v82, "__wrapped__", current)
    module._restart_authority_monitor = restart_monitor_v82
    return True


def reconcile_once() -> dict[str, bool]:
    with _LOCK:
        return {
            "entrypoint": _patch_entrypoint_authority(),
            "observer": _patch_authority_observer(),
            "v39_monitor": _patch_v39_monitor_restart(),
        }


def install_import_hook() -> bool:
    state = reconcile_once()
    os.environ["NIJA_WRITER_SINGLE_OWNER_CONVERGENCE_V82_INSTALLED"] = "1"
    LOGGER.critical(
        "WRITER_SINGLE_OWNER_CONVERGENCE_V82_INSTALLED marker=%s entrypoint=%s observer=%s v39_monitor=%s lock_owner=entrypoint_only secondary_lock_mutation=false blind_generation_adoption=false",
        MARKER,
        state["entrypoint"],
        state["observer"],
        state["v39_monitor"],
    )
    return bool(all(state.values()))


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "reconcile_once",
    "_exact_runtime_owner",
    "_patch_entrypoint_authority",
    "_patch_authority_observer",
    "_patch_v39_monitor_restart",
]
