"""Runtime capital/position/user-registry liveness repair v267.

Production deployment 36d4586 proved that the canonical writer and core can be
healthy, all three platform brokers can be connected, and the runtime can still
remain fail-closed because three process-local liveness owners stop making
progress:

* v137 records only a boolean when its publication-deadline monitor starts.  If
  that daemon exits, later installer/audit passes see the stale boolean and can
  never restart the monitor, so a formerly valid three-broker capital snapshot
  can expire without a replacement publication.
* v108 records position-sync single-flight ownership in a set.  A stale key with
  no live worker can suppress every later authoritative Kraken reconciliation.
* a canonical MultiAccountBrokerManager created after an earlier prepared
  manager can contain the live platform brokers while its registration-only
  user maps are empty.  v86/v90 then correctly see zero users and have nothing
  to reconnect even though enabled user configuration still exists.

v267 repairs only those liveness/ownership gaps.  It does not extend capital
freshness, publish capital, mark a position fetch successful, fabricate an empty
position snapshot, connect a user broker, create credentials, grant nonce or
execution authority, clear a kill switch, or force activation/trading.
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

LOGGER = logging.getLogger("nija.runtime_capital_position_liveness_v267")
MARKER = "20260828-runtime-capital-position-liveness-v267"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_POSITION_LIVENESS_V267_READY"
_PATCH_ATTR = "_nija_runtime_capital_position_liveness_v267"
_V137_THREAD_ATTR = "_nija_capital_publication_deadline_v137_thread"
_V137_THREAD_NAME = "capital-publication-deadline-v137"
_LOCK = threading.RLock()
_INSTALLED = False
_POSITION_ACTIVE_MISSING_SINCE: dict[tuple[int, int], float] = {}
_USER_REHYDRATE_NEXT_AT: dict[int, float] = {}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled", "y"}


def _alive(thread: Any) -> bool:
    reader = getattr(thread, "is_alive", None)
    try:
        return bool(reader()) if callable(reader) else False
    except Exception:
        return False


def _canonical_manager() -> Any:
    """Return the canonical manager without creating a compatibility mirror."""
    module = sys.modules.get("bot.multi_account_broker_manager")
    if not isinstance(module, ModuleType):
        try:
            module = importlib.import_module("bot.multi_account_broker_manager")
        except Exception:
            return None
    getter = getattr(module, "get_broker_manager", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            pass
    return getattr(module, "_manager", None) or getattr(
        module, "multi_account_broker_manager", None
    )


def _thread_targets_manager(thread: Any, manager: Any) -> bool:
    """Prove a live legacy v137 thread closes over this exact manager."""
    if not _alive(thread) or str(getattr(thread, "name", "")) != _V137_THREAD_NAME:
        return False
    target = getattr(thread, "_target", None)
    closure = getattr(target, "__closure__", None)
    if not closure:
        return False
    for cell in closure:
        try:
            if cell.cell_contents is manager:
                return True
        except Exception:
            continue
    return False


def _find_v137_thread(manager: Any) -> Any:
    stored = getattr(manager, _V137_THREAD_ATTR, None)
    if _alive(stored):
        return stored
    for thread in threading.enumerate():
        if _thread_targets_manager(thread, manager):
            return thread
    return None


def _manager_stopping(manager: Any) -> bool:
    stop = getattr(manager, "_capital_watchdog_stop", None)
    checker = getattr(stop, "is_set", None)
    try:
        if callable(checker) and checker():
            return True
    except Exception:
        return True
    return _truthy(os.environ.get("NIJA_PROCESS_EXIT_REQUESTED", "0"))


def _patch_v137_monitor() -> bool:
    """Make the v137 started latch prove a live manager-owned daemon."""
    try:
        v137 = importlib.import_module("bot.capital_publication_deadline_v137_patch")
    except Exception as exc:
        LOGGER.error(
            "CAPITAL_V267_V137_IMPORT_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    current = getattr(v137, "_start_deadline_monitor", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def start_deadline_monitor_v267(manager: Any) -> bool:
        live = _find_v137_thread(manager)
        if live is not None:
            setattr(manager, _V137_THREAD_ATTR, live)
            setattr(manager, "_nija_capital_publication_deadline_v137_started", True)
            return True

        if _manager_stopping(manager):
            LOGGER.info(
                "CAPITAL_V267_MONITOR_RESTART_SKIPPED marker=%s reason=manager_stopping "
                "freshness_extended=false trading_fail_closed=true",
                MARKER,
            )
            return False

        stale_latch = bool(
            getattr(manager, "_nija_capital_publication_deadline_v137_started", False)
        )
        if stale_latch:
            # The legacy latch is not authority.  Clear it only after proving no
            # live v137 thread targets this exact manager.
            setattr(manager, "_nija_capital_publication_deadline_v137_started", False)
            LOGGER.critical(
                "CAPITAL_V267_STALE_MONITOR_LATCH_CLEARED marker=%s "
                "live_manager_thread=false stale_boolean_only=true "
                "capital_mutated=false freshness_extended=false",
                MARKER,
            )

        started = bool(original(manager))
        live = _find_v137_thread(manager)
        if live is not None:
            setattr(manager, _V137_THREAD_ATTR, live)
        ready = bool(started and live is not None)
        LOGGER.critical(
            "CAPITAL_V267_MONITOR_LIVENESS marker=%s ready=%s restarted=%s "
            "canonical_v137_only=true active_writer_policy_preserved=true "
            "publication_expiry_extended=false freshness_extended=false",
            MARKER,
            str(ready).lower(),
            str(stale_latch).lower(),
        )
        return ready

    setattr(start_deadline_monitor_v267, _PATCH_ATTR, True)
    setattr(start_deadline_monitor_v267, "__wrapped__", original)
    v137._start_deadline_monitor = start_deadline_monitor_v267
    return True


def _ensure_v137_monitor() -> bool:
    manager = _canonical_manager()
    if manager is None:
        # Installation is still valid before manager construction.  A later
        # post-import iteration will re-run this exact check.
        return True
    try:
        v137 = importlib.import_module("bot.capital_publication_deadline_v137_patch")
        starter = getattr(v137, "_start_deadline_monitor", None)
        if not callable(starter):
            return False
        if _manager_stopping(manager):
            return True
        return bool(starter(manager))
    except Exception as exc:
        LOGGER.warning(
            "CAPITAL_V267_MONITOR_ENSURE_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _position_worker_grace_s() -> float:
    try:
        value = float(os.environ.get("NIJA_POSITION_SYNC_STALE_ACTIVE_GRACE_S", "15") or 15)
    except (TypeError, ValueError):
        value = 15.0
    return max(5.0, min(value, 60.0))


def _position_worker_alive(key: tuple[int, int], broker_name: str) -> bool:
    expected = f"platform-position-sync-v108-{str(broker_name or '').strip().lower()}"
    for thread in threading.enumerate():
        if str(getattr(thread, "name", "")) != expected or not _alive(thread):
            continue
        args = getattr(thread, "_args", ()) or ()
        # v108 workers receive (..., key, trigger).  Proving the key prevents a
        # worker for an obsolete manager/broker instance from satisfying this
        # single-flight.
        try:
            if any(value == key for value in args):
                return True
        except Exception:
            continue
    return False


def _clear_stale_v108_active(manager: Any, v108: ModuleType) -> int:
    active = getattr(v108, "_ACTIVE", None)
    lock = getattr(v108, "_LOCK", None)
    discover = getattr(v108, "_connected_unsynced_platform_brokers", None)
    if not isinstance(active, set) or lock is None or not callable(discover):
        return 0

    try:
        candidates = list(discover(manager) or [])
    except Exception:
        return 0

    now = time.monotonic()
    grace_s = _position_worker_grace_s()
    cleared = 0
    candidate_keys: set[tuple[int, int]] = set()
    for broker_name, broker in candidates:
        key = (id(manager), id(broker))
        candidate_keys.add(key)
        with lock:
            marked_active = key in active
        if not marked_active:
            _POSITION_ACTIVE_MISSING_SINCE.pop(key, None)
            continue
        if _position_worker_alive(key, broker_name):
            _POSITION_ACTIVE_MISSING_SINCE.pop(key, None)
            continue

        first_missing = _POSITION_ACTIVE_MISSING_SINCE.setdefault(key, now)
        missing_s = max(0.0, now - first_missing)
        if missing_s < grace_s:
            continue

        with lock:
            if key not in active or _position_worker_alive(key, broker_name):
                _POSITION_ACTIVE_MISSING_SINCE.pop(key, None)
                continue
            active.discard(key)
        _POSITION_ACTIVE_MISSING_SINCE.pop(key, None)
        cleared += 1
        LOGGER.critical(
            "POSITION_SYNC_V267_STALE_ACTIVE_CLEARED marker=%s broker=%s "
            "missing_worker_s=%.1f grace_s=%.1f stale_key_only=true "
            "position_mutated=false synthetic_success=false new_authoritative_retry_allowed=true",
            MARKER,
            broker_name,
            missing_s,
            grace_s,
        )

    # Prevent process-lifetime growth when managers/brokers are replaced.
    for key in tuple(_POSITION_ACTIVE_MISSING_SINCE):
        if key not in candidate_keys:
            _POSITION_ACTIVE_MISSING_SINCE.pop(key, None)
    return cleared


def _patch_v108_dispatch() -> bool:
    try:
        v108 = importlib.import_module("bot.platform_position_sync_v108_patch")
    except Exception as exc:
        LOGGER.error(
            "POSITION_SYNC_V267_V108_IMPORT_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False
    current = getattr(v108, "dispatch_platform_position_sync", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def dispatch_v267(manager: Any, *, trigger: str) -> int:
        _clear_stale_v108_active(manager, v108)
        return int(original(manager, trigger=trigger) or 0)

    setattr(dispatch_v267, _PATCH_ATTR, True)
    setattr(dispatch_v267, "__wrapped__", original)
    v108.dispatch_platform_position_sync = dispatch_v267
    return True


def _enabled_kraken_user_count() -> int:
    try:
        from config.user_loader import get_user_config_loader

        loader = get_user_config_loader()
        return sum(
            1
            for user in (loader.get_all_enabled_users() or [])
            if str(getattr(user, "broker_type", "") or "").strip().lower() == "kraken"
        )
    except Exception:
        return 0


def _registered_user_count(manager: Any) -> int:
    try:
        from bot.account_registry_snapshot import build_account_registry_snapshot

        return int(build_account_registry_snapshot(manager).user_registered)
    except Exception:
        return 0


def _user_rehydrate_backoff_s() -> float:
    try:
        value = float(os.environ.get("NIJA_USER_REGISTRY_REHYDRATE_RETRY_S", "30") or 30)
    except (TypeError, ValueError):
        value = 30.0
    return max(10.0, min(value, 300.0))


def _rehydrate_user_registry() -> bool:
    """Restore registration-only user records on a replacement canonical manager."""
    manager = _canonical_manager()
    if manager is None:
        return True
    configured = _enabled_kraken_user_count()
    if configured <= 0:
        # Explicit user kill switches flow through get_all_enabled_users(), so
        # zero is treated as intentional and never overridden here.
        return True
    if _registered_user_count(manager) > 0:
        _USER_REHYDRATE_NEXT_AT.pop(id(manager), None)
        return True

    # Do not replace partially populated registries.  This repair is only for
    # the exact empty-manager handoff observed in production.
    if any(
        bool(getattr(manager, attr, {}) or {})
        for attr in (
            "_all_user_brokers",
            "user_brokers",
            "_user_metadata",
            "_failed_user_connections",
            "_users_without_credentials",
        )
    ):
        LOGGER.warning(
            "USER_REGISTRY_V267_REHYDRATE_DEFERRED marker=%s reason=nonempty_unclassified_registry "
            "registered=0 configured_kraken=%d registry_mutated=false",
            MARKER,
            configured,
        )
        return True

    now = time.monotonic()
    key = id(manager)
    if now < _USER_REHYDRATE_NEXT_AT.get(key, 0.0):
        return True
    _USER_REHYDRATE_NEXT_AT[key] = now + _user_rehydrate_backoff_s()

    prepare = getattr(manager, "prepare_users_from_config", None)
    if not callable(prepare):
        LOGGER.warning(
            "USER_REGISTRY_V267_REHYDRATE_FAILED marker=%s reason=prepare_users_unavailable "
            "configured_kraken=%d broker_io=false trading_fail_closed=true",
            MARKER,
            configured,
        )
        return True

    try:
        prepared = int(prepare() or 0)
    except Exception as exc:
        LOGGER.warning(
            "USER_REGISTRY_V267_REHYDRATE_FAILED marker=%s error=%s:%s "
            "registration_only=true broker_connect_called=false trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return True

    registered = _registered_user_count(manager)
    if registered > 0:
        _USER_REHYDRATE_NEXT_AT.pop(key, None)
        LOGGER.critical(
            "USER_REGISTRY_V267_REHYDRATED marker=%s configured_kraken=%d prepared=%d registered=%d "
            "registration_only=true authenticated_connect_deferred_to_v86_v90=true "
            "credentials_fabricated=false connected_fabricated=false trading_eligibility_unchanged=true",
            MARKER,
            configured,
            prepared,
            registered,
        )
    else:
        LOGGER.warning(
            "USER_REGISTRY_V267_REHYDRATE_INCOMPLETE marker=%s configured_kraken=%d prepared=%d "
            "registered=0 next_retry_s=%.1f broker_io=false trading_fail_closed=true",
            MARKER,
            configured,
            prepared,
            _user_rehydrate_backoff_s(),
        )
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_position_liveness_v267"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        v137_ok = _patch_v137_monitor()
        v108_ok = _patch_v108_dispatch()
        manifest_ok = _patch_release_manifest()
        ready = bool(v137_ok and v108_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        _INSTALLED = ready

    # These are liveness actions, not readiness synthesis.  Keep them outside the
    # patch lock because manager/config operations may acquire their own locks.
    monitor_ok = _ensure_v137_monitor() if v137_ok else False
    user_guard_ok = _rehydrate_user_registry()

    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_CAPITAL_POSITION_LIVENESS_V267 marker=%s ready=%s "
        "v137_monitor_patch=%s v137_monitor_live=%s v108_stale_active_recovery=%s "
        "user_registry_rehydrate_guard=%s capital_freshness_extended=false "
        "publication_expiry_extended=false position_success_fabricated=false "
        "user_connected_fabricated=false execution_authority_unchanged=true "
        "writer_nonce_risk_killswitch_min_notional_order_fill_gates_unchanged=true "
        "forced_trade=false forced_activation=false safety_gates_bypassed=false",
        MARKER,
        str(ready).lower(),
        str(v137_ok).lower(),
        str(monitor_ok).lower(),
        str(v108_ok).lower(),
        str(user_guard_ok).lower(),
    )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_patch_v137_monitor",
    "_ensure_v137_monitor",
    "_patch_v108_dispatch",
    "_clear_stale_v108_active",
    "_position_worker_alive",
    "_rehydrate_user_registry",
    "_enabled_kraken_user_count",
    "_registered_user_count",
]
