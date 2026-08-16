"""Production convergence repair v116.

Closes remaining activation, writer-lifecycle, and position-sync races without
fabricating readiness or weakening any execution gate.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_convergence_v116")
MARKER = "20260816-runtime-convergence-v116"
_LOCK = threading.RLock()
_IMPORT_LOCAL = threading.local()
_IMPORT_FLAG = "_NIJA_RUNTIME_CONVERGENCE_V116_IMPORT_HOOK"
_PATCH_ATTR = "_nija_runtime_convergence_v116"
_BROKER_LOCKS: dict[int, threading.RLock] = {}
_BROKER_LOCKS_GUARD = threading.Lock()


def _loaded(*names: str) -> ModuleType | None:
    for name in names:
        mod = sys.modules.get(name)
        if isinstance(mod, ModuleType):
            return mod
    return None


def _import(*names: str) -> ModuleType | None:
    mod = _loaded(*names)
    if mod is not None:
        return mod
    for name in names:
        try:
            mod = importlib.import_module(name)
        except Exception:
            continue
        if isinstance(mod, ModuleType):
            return mod
    return None


def _readiness_complete() -> tuple[bool, list[str]]:
    mod = _import("bot.readiness_table", "readiness_table")
    if mod is None:
        return False, ["readiness_table_unavailable"]
    try:
        snapshot = dict(mod.snapshot() or {})
    except Exception:
        return False, ["readiness_snapshot_unavailable"]
    pending = sorted(str(k) for k, v in snapshot.items() if not bool(v))
    return bool(snapshot) and not pending, pending


def _patch_activation_bridge() -> bool:
    mod = _loaded("bot.activation_snapshot_bridge_patch", "activation_snapshot_bridge_patch")
    if mod is None:
        return True
    current = getattr(mod, "_concrete_activation_gates_pass", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return callable(current)

    @wraps(current)
    def guarded(tsm_module: Any) -> tuple[bool, str]:
        ok, detail = current(tsm_module)
        if not ok:
            return bool(ok), str(detail or "blocked")
        ready, pending = _readiness_complete()
        if not ready:
            LOGGER.critical(
                "ACTIVATION_BRIDGE_V116_BLOCKED marker=%s pending=%s fail_closed=true",
                MARKER,
                pending,
            )
            return False, f"canonical_readiness_incomplete:{','.join(pending)}"
        return True, ""

    setattr(guarded, _PATCH_ATTR, True)
    mod._concrete_activation_gates_pass = guarded
    return True


def _patch_trading_state_machine() -> bool:
    mod = _loaded("bot.trading_state_machine", "trading_state_machine")
    if mod is None:
        return True
    cls = getattr(mod, "TradingStateMachine", None)
    current = getattr(cls, "commit_activation", None) if isinstance(cls, type) else None
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return callable(current)

    @wraps(current)
    def commit_guarded(self: Any, *args: Any, **kwargs: Any):
        try:
            state = self.get_current_state()
            state_name = str(getattr(state, "value", state) or "").upper()
        except Exception:
            state_name = ""
        if state_name != "LIVE_ACTIVE":
            ready, pending = _readiness_complete()
            if not ready:
                LOGGER.info(
                    "ACTIVATION_COMMIT_V116_PENDING marker=%s pending=%s direct_live_bypass=false",
                    MARKER,
                    pending,
                )
                return False
        return current(self, *args, **kwargs)

    setattr(commit_guarded, _PATCH_ATTR, True)
    cls.commit_activation = commit_guarded
    return True


def _bootstrap_running_supervised() -> bool:
    mod = _import("bot.bootstrap_state_machine", "bootstrap_state_machine")
    if mod is None:
        return False
    try:
        fsm = mod.get_bootstrap_fsm()
        value = getattr(getattr(fsm, "state", None), "value", getattr(fsm, "current_state", ""))
        return str(getattr(value, "value", value)) == "RUNNING_SUPERVISED"
    except Exception:
        return False


def _writer_core_healthy(runtime: Any, trading_thread: Any) -> bool:
    if runtime is None or bool(getattr(runtime, "lost", True)) or not bool(getattr(runtime, "acquired", False)):
        return False
    if bool(getattr(runtime, "_local_fallback", False)):
        return False
    try:
        if trading_thread is None or not trading_thread.is_alive():
            return False
    except Exception:
        return False
    if os.environ.get("NIJA_PROCESS_EXIT_REQUESTED", "").strip().lower() in {"1", "true", "yes"}:
        return False
    return True


def _patch_bot_main() -> bool:
    mod = _loaded("bot.bot_main", "bot_main")
    if mod is None:
        return True
    current = getattr(mod, "_perform_post_core_activation_convergence", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return callable(current)

    @wraps(current)
    def supervised_pending(runtime: Any, trading_thread: Any, *args: Any, **kwargs: Any) -> bool:
        result = bool(current(runtime, trading_thread, *args, **kwargs))
        if result:
            return True
        if _writer_core_healthy(runtime, trading_thread) and _bootstrap_running_supervised():
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
            LOGGER.critical(
                "POST_CORE_V116_SUPERVISED_PENDING marker=%s writer_core_healthy=true bootstrap=RUNNING_SUPERVISED trading_fail_closed=true",
                MARKER,
            )
            return True
        return False

    setattr(supervised_pending, _PATCH_ATTR, True)
    mod._perform_post_core_activation_convergence = supervised_pending
    return True


def _broker_lock(broker: Any) -> threading.RLock:
    key = id(broker)
    with _BROKER_LOCKS_GUARD:
        return _BROKER_LOCKS.setdefault(key, threading.RLock())


def _freshness_s() -> float:
    try:
        return max(0.1, min(10.0, float(os.environ.get("NIJA_POSITION_SYNC_DUPLICATE_COALESCE_S", "3") or 3.0)))
    except (TypeError, ValueError):
        return 3.0


def _patch_position_sync() -> bool:
    mod = _loaded("bot.startup_position_sync", "startup_position_sync")
    if mod is None:
        return True
    current = getattr(mod, "_adopt_broker_positions", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return callable(current)

    @wraps(current)
    def single_flight(broker: Any, broker_name: str, eps: Any) -> int:
        with _broker_lock(broker):
            now = time.monotonic()
            last_ok = float(getattr(broker, "_nija_position_sync_v116_last_ok", 0.0) or 0.0)
            if bool(getattr(broker, "_startup_position_sync_adopted", False)) and last_ok > 0 and now - last_ok <= _freshness_s():
                LOGGER.info(
                    "POSITION_SYNC_V116_COALESCED marker=%s broker=%s age_s=%.3f duplicate_only=true",
                    MARKER,
                    broker_name,
                    max(0.0, now - last_ok),
                )
                return 0
            try:
                result = int(current(broker, broker_name, eps) or 0)
            except BaseException:
                setattr(broker, "_startup_position_sync_fetch_ok", False)
                raise
            if bool(getattr(broker, "_startup_position_sync_adopted", False)):
                setattr(broker, "_nija_position_sync_v116_last_ok", time.monotonic())
                setattr(broker, "_startup_position_sync_fetch_ok", True)
                setattr(broker, "_startup_position_sync_error", None)
            return result

    setattr(single_flight, _PATCH_ATTR, True)
    mod._adopt_broker_positions = single_flight
    return True


def _patch_writer_state() -> bool:
    mod = _loaded("bot.entrypoint_writer_authority", "entrypoint_writer_authority")
    if mod is None:
        return True
    cls = getattr(mod, "EntrypointWriterAuthority", None)
    current = getattr(cls, "_set_writer_state", None) if isinstance(cls, type) else None
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return callable(current)

    @wraps(current)
    def no_resurrection(self: Any, state: Any, *args: Any, **kwargs: Any):
        requested = str(getattr(state, "value", state) or "").upper()
        stop = getattr(self, "_stop", None)
        lost = getattr(self, "_lost", None)
        stop_set = bool(callable(getattr(stop, "is_set", None)) and stop.is_set())
        lost_set = bool(callable(getattr(lost, "is_set", None)) and lost.is_set())
        if requested != "LOST" and (stop_set or lost_set):
            LOGGER.warning(
                "WRITER_STATE_V116_RESURRECTION_BLOCKED marker=%s requested=%s stop=%s lost=%s",
                MARKER,
                requested,
                stop_set,
                lost_set,
            )
            return None
        return current(self, state, *args, **kwargs)

    setattr(no_resurrection, _PATCH_ATTR, True)
    cls._set_writer_state = no_resurrection
    return True


def _patch_kraken_user_eligibility() -> bool:
    mod = _loaded("bot.kraken_all_account_supervision_v86", "kraken_all_account_supervision_v86")
    if mod is None:
        return True
    current = getattr(mod, "_reconcile_post_connect", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return callable(current)

    @wraps(current)
    def reconcile_guarded(manager: Any, user_id: str, broker_type: Any, broker: Any) -> None:
        current(manager, user_id, broker_type, broker)
        if bool(getattr(broker, "_startup_position_sync_adopted", False)):
            return
        key = (user_id, broker_type)
        metadata = getattr(manager, "_user_metadata", None)
        if isinstance(metadata, dict):
            metadata.setdefault(user_id, {}).setdefault("brokers", {})[broker_type] = False
        blocked = getattr(manager, "_capital_blocked_users", None)
        if isinstance(blocked, dict):
            blocked[key] = "position_sync_incomplete"
        LOGGER.warning(
            "USER_TRADING_ELIGIBILITY_V116_BLOCKED marker=%s account=user:%s:kraken reason=position_sync_incomplete execution_fail_closed=true",
            MARKER,
            user_id,
        )

    setattr(reconcile_guarded, _PATCH_ATTR, True)
    mod._reconcile_post_connect = reconcile_guarded
    return True


def _patch_loaded() -> bool:
    return all((
        _patch_activation_bridge(),
        _patch_trading_state_machine(),
        _patch_bot_main(),
        _patch_position_sync(),
        _patch_writer_state(),
        _patch_kraken_user_eligibility(),
    ))


def install_import_hook() -> bool:
    with _LOCK:
        ready = _patch_loaded()
        if not getattr(builtins, _IMPORT_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if getattr(_IMPORT_LOCAL, "active", False):
                    return result
                text = str(name or "")
                if any(token in text for token in (
                    "activation_snapshot_bridge",
                    "trading_state_machine",
                    "bot_main",
                    "startup_position_sync",
                    "entrypoint_writer_authority",
                    "kraken_all_account_supervision",
                )):
                    _IMPORT_LOCAL.active = True
                    try:
                        _patch_loaded()
                    finally:
                        _IMPORT_LOCAL.active = False
                return result

            builtins.__import__ = importing
            setattr(builtins, _IMPORT_FLAG, True)
        os.environ["NIJA_RUNTIME_CONVERGENCE_V116_INSTALLED"] = "1"
        LOGGER.critical(
            "RUNTIME_CONVERGENCE_V116_INSTALLED marker=%s readiness_bypass=false supervised_pending=true position_sync_single_flight=true writer_resurrection=false user_position_sync_eligibility=true initial_patch_ready=%s",
            MARKER,
            ready,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook"]
