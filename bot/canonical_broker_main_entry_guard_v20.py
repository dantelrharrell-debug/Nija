"""Direct canonical broker-manager guard for the active bot_main entrypoint.

This guard repairs a startup ordering failure where the legacy v18 handoff wrapper
can be lost or can encounter an InitRegistry key owned by a different manager
instance. It runs only after SelfHealingStartup reports a connected broker, repairs
the canonical manager's capital-FSM latch when necessary, and requires a fresh
positive CapitalAuthority snapshot before returning success in live mode.

It never grants writer authority, forces LIVE_ACTIVE, fabricates balances, creates
orders, or bypasses normal risk/state-machine gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.canonical_broker_main_guard")
_MARKER = "20260723-canonical-broker-main-guard-v20"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False
_STARTUP_WRAP_ATTR = "_nija_canonical_broker_main_guard_startup_v20"
_MAIN_WRAP_ATTR = "_nija_canonical_broker_main_guard_main_v20"


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _canonical_manager() -> Any:
    module = importlib.import_module("bot.multi_account_broker_manager")
    manager = getattr(module, "multi_account_broker_manager", None)
    if manager is None:
        getter = getattr(module, "get_broker_manager", None)
        manager = getter() if callable(getter) else None
    if manager is None:
        raise RuntimeError("canonical MultiAccountBrokerManager singleton unavailable")
    return manager


def _authority_snapshot(manager: Any) -> dict[str, Any]:
    module = importlib.import_module("bot.capital_authority")
    getter = getattr(module, "get_capital_authority", None)
    authority = getter() if callable(getter) else None
    if authority is None:
        return {
            "hydrated": False,
            "capital": 0.0,
            "stale": True,
            "valid_brokers": int(getattr(manager, "_capital_last_valid_brokers", 0) or 0),
        }

    try:
        capital = float(authority.get_real_capital() or 0.0)
    except Exception:
        capital = float(getattr(authority, "total_capital", 0.0) or 0.0)
    try:
        stale = bool(authority.is_stale())
    except Exception:
        stale = True

    hydrated_raw = getattr(authority, "is_hydrated", False)
    try:
        hydrated = bool(hydrated_raw() if callable(hydrated_raw) else hydrated_raw)
    except Exception:
        hydrated = False

    valid = int(getattr(manager, "_capital_last_valid_brokers", 0) or 0)
    if valid <= 0:
        for attr in ("valid_brokers", "broker_count", "_valid_broker_count"):
            try:
                candidate = int(getattr(authority, attr, 0) or 0)
            except Exception:
                candidate = 0
            if candidate > 0:
                valid = candidate
                break

    return {
        "hydrated": hydrated,
        "capital": capital,
        "stale": stale,
        "valid_brokers": valid,
    }


def _manager_contract(manager: Any) -> tuple[bool, str]:
    if not bool(getattr(manager, "_fsm_initialized", False)):
        return False, "fsm_not_initialized"

    has_sources = getattr(manager, "has_registered_sources", None)
    if callable(has_sources) and not bool(has_sources()):
        return False, "no_registered_platform_source"

    attempted = getattr(manager, "has_attempted_connections", None)
    if callable(attempted) and not bool(attempted()):
        return False, "broker_registration_not_finalized"

    return True, "manager_ready"


def _repair_capital_fsm_latch(manager: Any, cause: BaseException | None = None) -> bool:
    """Repair only the canonical manager's missing capital-FSM wiring.

    InitRegistry is process-global. If a duplicate or early manager consumed the
    MABM_CAPITAL_FSM key, the canonical manager can remain unwired forever.
    _init_capital_fsm is idempotent, so calling it on the canonical singleton is
    a narrow repair that does not reset the registry or create another manager.
    """

    if bool(getattr(manager, "_fsm_initialized", False)):
        return True

    repair = getattr(manager, "_init_capital_fsm", None)
    if not callable(repair):
        return False

    logger.critical(
        "CANONICAL_BROKER_FSM_LATCH_REPAIR_BEGIN marker=%s cause=%s",
        _MARKER,
        f"{type(cause).__name__}:{cause}" if cause is not None else "missing_fsm_after_initialize",
    )
    repair()
    repaired = bool(getattr(manager, "_fsm_initialized", False))
    logger.critical(
        "CANONICAL_BROKER_FSM_LATCH_REPAIR_RESULT marker=%s repaired=%s",
        _MARKER,
        repaired,
    )
    return repaired


def _initialize_manager(manager: Any) -> None:
    initialize = getattr(manager, "initialize", None)
    if not callable(initialize):
        raise RuntimeError("MultiAccountBrokerManager.initialize is unavailable")

    if bool(getattr(manager, "_fsm_initialized", False)):
        return

    try:
        initialize()
    except Exception as first_exc:
        if not _repair_capital_fsm_latch(manager, first_exc):
            raise
        logger.warning(
            "CANONICAL_BROKER_MANAGER_INITIALIZE_RETRY marker=%s first_error=%s",
            _MARKER,
            f"{type(first_exc).__name__}:{first_exc}",
        )
        initialize()

    if not bool(getattr(manager, "_fsm_initialized", False)):
        if not _repair_capital_fsm_latch(manager):
            raise RuntimeError("canonical broker manager contract failed: fsm_not_initialized")


def _refresh_capital(manager: Any) -> None:
    refresh = getattr(manager, "refresh_capital_authority", None)
    if not callable(refresh):
        return
    try:
        refresh(trigger="bot_main_direct_canonical_handoff")
    except TypeError:
        refresh("bot_main_direct_canonical_handoff")


def _initialize_canonical_runtime(
    broker: Any,
    broker_name: str,
) -> tuple[bool, Any, str]:
    manager = _canonical_manager()

    logger.critical(
        "CANONICAL_BROKER_MAIN_GUARD_INITIALIZING marker=%s broker=%s thread=%s",
        _MARKER,
        broker_name or type(broker).__name__,
        threading.current_thread().name,
    )
    _initialize_manager(manager)

    manager_ok, manager_reason = _manager_contract(manager)
    if not manager_ok:
        raise RuntimeError(f"canonical broker manager contract failed: {manager_reason}")

    timeout_s = max(
        1.0,
        float(os.environ.get("NIJA_CANONICAL_BROKER_BOOTSTRAP_TIMEOUT_S", "60") or 60),
    )
    poll_s = max(
        0.1,
        float(os.environ.get("NIJA_CANONICAL_BROKER_BOOTSTRAP_POLL_S", "1") or 1),
    )
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}

    while True:
        last = _authority_snapshot(manager)
        live_mode = (
            _truthy("LIVE_CAPITAL_VERIFIED")
            and not _truthy("DRY_RUN_MODE")
            and not _truthy("PAPER_MODE")
        )
        ready = bool(last["hydrated"]) and not bool(last["stale"])
        if live_mode:
            ready = (
                ready
                and float(last["capital"]) > 0.0
                and int(last["valid_brokers"]) >= 1
            )

        if ready:
            os.environ["NIJA_CANONICAL_BROKER_BOOTSTRAP_READY"] = "1"
            os.environ["NIJA_CANONICAL_BROKER_BOOTSTRAP_MARKER"] = _MARKER
            os.environ["NIJA_CANONICAL_BROKER_MAIN_GUARD_READY"] = "1"
            logger.critical(
                "CANONICAL_BROKER_MAIN_GUARD_READY marker=%s broker=%s hydrated=%s "
                "capital=%.8f stale=%s valid_brokers=%s fsm_initialized=true",
                _MARKER,
                broker_name or type(broker).__name__,
                last["hydrated"],
                float(last["capital"]),
                last["stale"],
                last["valid_brokers"],
            )
            return True, broker, broker_name

        if time.monotonic() >= deadline:
            break

        try:
            _refresh_capital(manager)
        except Exception as exc:
            logger.warning(
                "CANONICAL_BROKER_MAIN_GUARD_REFRESH_WAITING marker=%s err=%s state=%s",
                _MARKER,
                exc,
                last,
            )
        time.sleep(poll_s)

    os.environ["NIJA_CANONICAL_BROKER_BOOTSTRAP_READY"] = "0"
    os.environ["NIJA_CANONICAL_BROKER_MAIN_GUARD_READY"] = "0"
    raise RuntimeError(
        "canonical broker capital hydration timed out "
        f"after {timeout_s:.1f}s state={last}"
    )


def _unwrap_legacy_startup(current: Callable[..., Any]) -> Callable[..., Any]:
    """Return the original startup function beneath legacy wrapper layers."""

    seen: set[int] = set()
    base = current
    while callable(getattr(base, "__wrapped__", None)) and id(base) not in seen:
        seen.add(id(base))
        candidate = getattr(base, "__wrapped__")
        if not callable(candidate):
            break
        base = candidate
    return base


def _patch_startup(module: ModuleType) -> bool:
    current = getattr(module, "_run_self_healing_startup", None)
    if not callable(current):
        return False
    if bool(getattr(current, _STARTUP_WRAP_ATTR, False)):
        return True

    base = _unwrap_legacy_startup(current)

    @wraps(base)
    def guarded_startup(*args: Any, **kwargs: Any):
        ok, broker, broker_name = base(*args, **kwargs)
        if not ok:
            return ok, broker, broker_name
        try:
            return _initialize_canonical_runtime(broker, broker_name)
        except Exception as exc:
            os.environ["NIJA_CANONICAL_BROKER_BOOTSTRAP_READY"] = "0"
            os.environ["NIJA_CANONICAL_BROKER_MAIN_GUARD_READY"] = "0"
            logger.critical(
                "CANONICAL_BROKER_MAIN_GUARD_FAILED marker=%s broker=%s err=%s "
                "trading_remains_fail_closed=true",
                _MARKER,
                broker_name or type(broker).__name__,
                exc,
                exc_info=True,
            )
            return False, None, ""

    setattr(guarded_startup, _STARTUP_WRAP_ATTR, True)
    setattr(guarded_startup, "__wrapped__", base)
    setattr(module, "_run_self_healing_startup", guarded_startup)
    logger.critical(
        "CANONICAL_BROKER_MAIN_GUARD_STARTUP_PATCHED marker=%s module=%s "
        "legacy_layers_unwrapped=%s",
        _MARKER,
        module.__name__,
        base is not current,
    )
    return True


def _patch_main(module: ModuleType) -> bool:
    current = getattr(module, "main", None)
    if not callable(current):
        return False
    if bool(getattr(current, _MAIN_WRAP_ATTR, False)):
        return True

    @wraps(current)
    def guarded_main(*args: Any, **kwargs: Any):
        if not _patch_startup(module):
            logger.critical(
                "CANONICAL_BROKER_MAIN_GUARD_REPATCH_FAILED marker=%s "
                "trading_remains_fail_closed=true",
                _MARKER,
            )
            return 1
        return current(*args, **kwargs)

    setattr(guarded_main, _MAIN_WRAP_ATTR, True)
    setattr(guarded_main, "__wrapped__", current)
    setattr(module, "main", guarded_main)
    logger.critical(
        "CANONICAL_BROKER_MAIN_GUARD_MAIN_PATCHED marker=%s module=%s",
        _MARKER,
        module.__name__,
    )
    return True


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        module = importlib.import_module("bot.bot_main")
        startup_patched = _patch_startup(module)
        main_patched = _patch_main(module)
        _INSTALLED = bool(startup_patched and main_patched)
        os.environ["NIJA_CANONICAL_BROKER_MAIN_GUARD_INSTALLED"] = (
            "1" if _INSTALLED else "0"
        )
        logger.critical(
            "CANONICAL_BROKER_MAIN_GUARD_INSTALLED marker=%s startup_patched=%s "
            "main_patched=%s",
            _MARKER,
            startup_patched,
            main_patched,
        )
        return _INSTALLED


def install() -> bool:
    return install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_initialize_canonical_runtime",
    "_initialize_manager",
    "_repair_capital_fsm_latch",
    "_unwrap_legacy_startup",
    "_patch_startup",
    "_patch_main",
]
