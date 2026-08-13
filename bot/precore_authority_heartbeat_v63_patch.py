"""Pre-core authority heartbeat and owned-lockdown recovery repair v64.

The canonical writer authority intentionally publishes ``NIJA_CORE_THREAD_ALIVE=0``
while the process still owns a healthy writer lease but the real trading core has
not been launched/registered yet.  The independent authority heartbeat must not
interpret that documented pre-core state as a dead core.

v64 preserves the narrow v63 startup grace and closes two follow-on races:

* the temporary pre-core environment suppression never overwrites a concurrent
  core-registration write (for example ``NIJA_CORE_THREAD_ALIVE=1``);
* when AuthorityHeartbeatMonitor recovers from a transient lockdown while the
  canonical writer still owns a healthy lease, the heartbeat-owned FSM/SEAK
  latches are released only after a fresh strict authority proof and a clear
  kill switch.  Recovery returns the trading FSM to OFF, never LIVE_ACTIVE, so
  normal activation gates must reconverge before any new dispatch is possible.

Operator/kill-switch emergency stops and SEAK halts with any non-heartbeat reason
remain untouched and fail closed.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.precore_authority_heartbeat_v63")
MARKER = "20260812-precore-authority-heartbeat-v64"
_LOCK = threading.RLock()
_PATCH_ATTR = "_nija_precore_authority_heartbeat_v64"
_START_PATCH_ATTR = "_nija_authority_heartbeat_owned_recovery_v64"
_CALLBACK_PATCH_ATTR = "_nija_authority_heartbeat_owned_callback_v64"
_HOOK_FLAG = "_NIJA_PRECORE_AUTHORITY_HEARTBEAT_V64_IMPORT_HOOK"
_MODULE_NAMES = ("bot.authority_heartbeat", "authority_heartbeat")
_OWNED_STOP_ENV = "NIJA_AUTHORITY_HEARTBEAT_OWNED_STOP"
_OWNED_REASON_ENV = "NIJA_AUTHORITY_HEARTBEAT_OWNED_STOP_REASON"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _canonical_writer_runtime() -> Any:
    for name in ("bot.entrypoint_writer_authority", "entrypoint_writer_authority"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        getter = getattr(module, "get_entrypoint_writer_authority", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
    return None


def _core_live(runtime: Any) -> bool:
    if runtime is None or not bool(getattr(runtime, "_core_thread_registered", False)):
        return False
    core = getattr(runtime, "_core_thread", None)
    alive = getattr(core, "is_alive", None) if core is not None else None
    if not callable(alive):
        return False
    try:
        return bool(alive())
    except Exception:
        return False


def _precore_grace_active() -> tuple[bool, str]:
    runtime = _canonical_writer_runtime()
    if runtime is None:
        return False, "writer_runtime_unavailable"

    # Grace is meaningful only after the canonical distributed writer has
    # actually been acquired.  A merely-instantiated singleton is not authority.
    if not bool(getattr(runtime, "acquired", False)):
        return False, "writer_not_acquired"
    if bool(getattr(runtime, "lost", False)):
        return False, "writer_lost"
    if str(getattr(runtime, "terminal_startup_failure_reason", "") or "").strip():
        return False, "terminal_startup_failure"
    if bool(getattr(runtime, "_scan_deadline_exceeded", False)):
        return False, "scan_deadline_exceeded"

    core = getattr(runtime, "_core_thread", None)
    registered = bool(getattr(runtime, "_core_thread_registered", False))
    if core is not None or registered:
        return False, "core_handoff_started"

    bot_main = sys.modules.get("bot.bot_main") or sys.modules.get("bot_main")
    if isinstance(bot_main, ModuleType):
        shutdown = getattr(bot_main, "_shutdown_event", None)
        if shutdown is not None and callable(getattr(shutdown, "is_set", None)):
            try:
                if shutdown.is_set():
                    return False, "shutdown_requested"
            except Exception:
                return False, "shutdown_state_unavailable"
        if bool(getattr(bot_main, "_startup_complete", False)):
            return False, "startup_complete_without_core"

    return True, "startup_not_registered"


def _kill_switch_clear() -> tuple[bool, str]:
    try:
        try:
            from bot.kill_switch import get_kill_switch
        except ImportError:
            from kill_switch import get_kill_switch  # type: ignore[import]
        if bool(get_kill_switch().is_active()):
            return False, "kill_switch_active"
        return True, "kill_switch_clear"
    except Exception as exc:
        return False, f"kill_switch_probe_failed:{type(exc).__name__}:{exc}"


def _seak_status() -> tuple[Any, bool, str]:
    try:
        try:
            from bot.single_execution_authority_kernel import get_seak
        except ImportError:
            from single_execution_authority_kernel import get_seak  # type: ignore[import]
        seak = get_seak()
        halted = bool(getattr(seak, "is_halted", False))
        reason = ""
        snapshot = getattr(seak, "snapshot", None)
        if callable(snapshot):
            try:
                payload = snapshot() or {}
                if isinstance(payload, dict):
                    reason = str(payload.get("halt_reason") or "")
            except Exception:
                pass
        if not reason:
            reason = str(getattr(seak, "_halt_reason", "") or "")
        return seak, halted, reason
    except Exception as exc:
        return None, True, f"seak_probe_failed:{type(exc).__name__}:{exc}"


def _trading_state_machine() -> tuple[Any, Any, str]:
    try:
        try:
            from bot.trading_state_machine import get_state_machine, TradingState
        except ImportError:
            from trading_state_machine import get_state_machine, TradingState  # type: ignore[import]
        sm = get_state_machine()
        state = sm.get_current_state()
        value = str(getattr(state, "value", state) or "").strip().upper()
        return sm, TradingState, value
    except Exception as exc:
        return None, None, f"UNAVAILABLE:{type(exc).__name__}:{exc}"


def _recover_heartbeat_owned_stop(module: ModuleType, monitor: Any = None) -> tuple[bool, str]:
    """Release only a transient stop created by AuthorityHeartbeatMonitor.

    The monitor's built-in restart path restores heartbeat environment signals
    when the canonical writer still owns the lease.  Before releasing the FSM
    and SEAK latches created by the earlier lockdown, re-prove the complete
    authority check and current core liveness.  The FSM is returned to OFF so
    all normal activation/nonce/readiness gates must run again.
    """

    if not _truthy(_OWNED_STOP_ENV):
        return False, "heartbeat_owned_stop_marker_missing"

    runtime = _canonical_writer_runtime()
    if runtime is None or not bool(getattr(runtime, "acquired", False)):
        return False, "writer_not_acquired"
    if bool(getattr(runtime, "lost", False)):
        return False, "writer_lost"
    if not _core_live(runtime):
        return False, "core_not_live"

    try:
        timeout_s = max(
            0.1,
            float(os.environ.get("NIJA_AUTHORITY_HEARTBEAT_TIMEOUT_S", "5") or 5.0),
        )
    except (TypeError, ValueError):
        timeout_s = 5.0

    checker = getattr(module, "_check_authority_once", None)
    if not callable(checker):
        return False, "authority_checker_missing"
    try:
        authority_ok, authority_reason = checker(timeout_s)
    except Exception as exc:
        return False, f"authority_check_failed:{type(exc).__name__}:{exc}"
    if not bool(authority_ok):
        return False, f"authority_not_ready:{authority_reason or 'unknown'}"

    kill_clear, kill_reason = _kill_switch_clear()
    if not kill_clear:
        return False, kill_reason

    seak, seak_halted, seak_reason = _seak_status()
    if seak_halted and not str(seak_reason).startswith("AUTHORITY_HEARTBEAT_EXPIRED:"):
        return False, f"seak_halt_not_heartbeat_owned:{seak_reason or 'unknown'}"

    sm, TradingState, state_value = _trading_state_machine()
    if sm is None or TradingState is None:
        return False, state_value

    if state_value == "EMERGENCY_STOP":
        try:
            sm.transition_to(
                TradingState.OFF,
                f"authority heartbeat recovered; reactivation required marker={MARKER}",
            )
        except Exception as exc:
            return False, f"fsm_recovery_failed:{type(exc).__name__}:{exc}"
    elif state_value not in {"OFF", "LIVE_PENDING_CONFIRMATION", "LIVE_ACTIVE"}:
        # Unknown/nonstandard states are not rewritten by this recovery path.
        return False, f"fsm_state_not_recoverable:{state_value or 'unknown'}"

    # Resume SEAK only after the FSM is safely OFF (or already left the stale
    # emergency state).  This keeps order dispatch closed while normal activation
    # proofs reconverge.
    if seak_halted:
        resume = getattr(seak, "resume", None)
        if not callable(resume):
            return False, "seak_resume_missing"
        try:
            resume(caller="authority_heartbeat_recovery_v64")
        except Exception as exc:
            return False, f"seak_resume_failed:{type(exc).__name__}:{exc}"

    os.environ.pop(_OWNED_STOP_ENV, None)
    os.environ.pop(_OWNED_REASON_ENV, None)
    LOGGER.critical(
        "AUTHORITY_HEARTBEAT_OWNED_STOP_RECOVERED marker=%s "
        "writer_acquired=true core_live=true authority_proof=true kill_switch_clear=true "
        "fsm_reactivated=false seak_resumed=%s",
        MARKER,
        str(bool(seak_halted)).lower(),
    )
    return True, "heartbeat_owned_stop_recovered_to_fail_closed_off"


def _patch_authority_heartbeat(module: ModuleType) -> bool:
    changed = False

    current = getattr(module, "_check_authority_once", None)
    if callable(current) and not getattr(current, _PATCH_ATTR, False):
        @wraps(current)
        def check_authority_once_v64(timeout_s: float):
            raw = str(os.environ.get("NIJA_CORE_THREAD_ALIVE", "") or "").strip().lower()
            if raw and raw not in _TRUE:
                grace, reason = _precore_grace_active()
                if grace:
                    previous = os.environ.pop("NIJA_CORE_THREAD_ALIVE", None)
                    try:
                        result = current(timeout_s)
                    finally:
                        # Never clobber a concurrent core-registration/liveness
                        # publication.  Restore the old pre-core value only if no
                        # writer has published a newer signal while the check ran.
                        if previous is not None and "NIJA_CORE_THREAD_ALIVE" not in os.environ:
                            os.environ["NIJA_CORE_THREAD_ALIVE"] = previous
                    LOGGER.info(
                        "PRECORE_AUTHORITY_HEARTBEAT_GRACE marker=%s reason=%s "
                        "core_alive_signal=%s other_authority_gates_unchanged=true",
                        MARKER,
                        reason,
                        raw,
                    )
                    return result
            return current(timeout_s)

        setattr(check_authority_once_v64, _PATCH_ATTR, True)
        setattr(check_authority_once_v64, "__wrapped__", current)
        module._check_authority_once = check_authority_once_v64
        changed = True

    callback = getattr(module, "_default_lockdown_callback", None)
    if callable(callback) and not getattr(callback, _CALLBACK_PATCH_ATTR, False):
        @wraps(callback)
        def heartbeat_owned_lockdown(reason: str):
            os.environ[_OWNED_STOP_ENV] = "1"
            os.environ[_OWNED_REASON_ENV] = str(reason or "unknown")
            return callback(reason)

        setattr(heartbeat_owned_lockdown, _CALLBACK_PATCH_ATTR, True)
        setattr(heartbeat_owned_lockdown, "__wrapped__", callback)
        module._default_lockdown_callback = heartbeat_owned_lockdown
        existing = getattr(module, "_monitor_instance", None)
        if existing is not None and getattr(existing, "_lockdown_callback", None) is callback:
            existing._lockdown_callback = heartbeat_owned_lockdown
        changed = True

    cls = getattr(module, "AuthorityHeartbeatMonitor", None)
    original_start = getattr(cls, "start", None) if isinstance(cls, type) else None
    if callable(original_start) and not getattr(original_start, _START_PATCH_ATTR, False):
        @wraps(original_start)
        def start_with_owned_recovery(self: Any, *args: Any, **kwargs: Any):
            was_locked_down = bool(getattr(self, "_locked_down", False))
            result = original_start(self, *args, **kwargs)
            recovered_monitor = was_locked_down and not bool(getattr(self, "_locked_down", False))
            if recovered_monitor and _truthy(_OWNED_STOP_ENV):
                recovered, reason = _recover_heartbeat_owned_stop(module, self)
                if not recovered:
                    # The original monitor restart path is optimistic: it resets
                    # locked_down when the writer singleton still owns the lease.
                    # If the strict v64 proof fails, immediately restore lockdown
                    # signals so the process remains fail closed.
                    try:
                        self._locked_down = True
                    except Exception:
                        pass
                    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
                    os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = "0"
                    LOGGER.critical(
                        "AUTHORITY_HEARTBEAT_OWNED_STOP_RECOVERY_BLOCKED marker=%s "
                        "reason=%s trading_remains_fail_closed=true",
                        MARKER,
                        reason,
                    )
            return result

        setattr(start_with_owned_recovery, _START_PATCH_ATTR, True)
        setattr(start_with_owned_recovery, "__wrapped__", original_start)
        cls.start = start_with_owned_recovery
        changed = True

    if changed:
        LOGGER.critical(
            "PRECORE_AUTHORITY_HEARTBEAT_V64_PATCHED marker=%s module=%s "
            "precore_zero_grace=true concurrent_core_signal_preserved=true "
            "heartbeat_owned_recovery_fail_closed=true",
            MARKER,
            module.__name__,
        )
    return bool(changed or getattr(getattr(module, "_check_authority_once", None), _PATCH_ATTR, False))


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in _MODULE_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_authority_heartbeat(module) or changed
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if "authority_heartbeat" in str(name):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        # Keep the v63 readiness flag for callers already depending on it while
        # publishing a distinct v64 marker for rollout verification.
        os.environ["NIJA_PRECORE_AUTHORITY_HEARTBEAT_V63_READY"] = "1"
        os.environ["NIJA_PRECORE_AUTHORITY_HEARTBEAT_V64_READY"] = "1"
        LOGGER.critical(
            "PRECORE_AUTHORITY_HEARTBEAT_V64_INSTALLED marker=%s "
            "precore_grace_only=true authority_bypass=false owned_stop_recovery=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_precore_grace_active",
    "_recover_heartbeat_owned_stop",
]
