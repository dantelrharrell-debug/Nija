"""Repair the canonical broker-manager handoff in the active production entrypoint.

The production path (``main.py -> bot.bot -> bot.bot_main``) establishes writer
lineage and runs ``SelfHealingStartup``. SelfHealingStartup may connect platform
brokers through the process-wide ``MultiAccountBrokerManager`` but historically
returned before calling ``MultiAccountBrokerManager.initialize()``. That left the
capital FSM unwired, CapitalAuthority unhydrated, and all activation monitors
waiting forever.

This patch wraps only bot_main's self-healing handoff. After a broker connects it
initializes the existing canonical manager on the same bootstrap thread, verifies
broker registration and capital hydration, and then returns control to bot_main.
It does not force LIVE_ACTIVE, create a second broker, bypass writer/nonce gates,
or submit orders.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.canonical_broker_bootstrap_handoff")
_MARKER = "20260723-canonical-broker-bootstrap-v18"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False
_ORIGINAL: Optional[Callable[..., Any]] = None
_WRAP_ATTR = "_nija_canonical_broker_bootstrap_handoff_v18"


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


def _capital_snapshot(manager: Any) -> dict[str, Any]:
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
        "hydrated": bool(getattr(authority, "is_hydrated", False)),
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


def _refresh_capital(manager: Any) -> None:
    refresh = getattr(manager, "refresh_capital_authority", None)
    if not callable(refresh):
        return
    trigger = "bot_main_canonical_handoff"
    try:
        refresh(trigger=trigger)
    except TypeError:
        refresh(trigger)


def _initialize_canonical_broker_runtime(
    broker: Any,
    broker_name: str,
) -> tuple[bool, Any, str]:
    """Initialize the existing manager and verify the live capital contract."""

    manager = _canonical_manager()
    initialize = getattr(manager, "initialize", None)
    if not callable(initialize):
        raise RuntimeError("MultiAccountBrokerManager.initialize is unavailable")

    if not bool(getattr(manager, "_fsm_initialized", False)):
        logger.critical(
            "CANONICAL_BROKER_BOOTSTRAP_INITIALIZING marker=%s broker=%s thread=%s",
            _MARKER,
            broker_name or type(broker).__name__,
            threading.current_thread().name,
        )
        initialize()

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
        last = _capital_snapshot(manager)
        live_mode = (
            _truthy("LIVE_CAPITAL_VERIFIED")
            and not _truthy("DRY_RUN_MODE")
            and not _truthy("PAPER_MODE")
        )
        capital_ok = bool(last["hydrated"]) and not bool(last["stale"])
        if live_mode:
            capital_ok = (
                capital_ok
                and float(last["capital"]) > 0.0
                and int(last["valid_brokers"]) >= 1
            )

        if capital_ok:
            os.environ["NIJA_CANONICAL_BROKER_BOOTSTRAP_READY"] = "1"
            os.environ["NIJA_CANONICAL_BROKER_BOOTSTRAP_MARKER"] = _MARKER
            logger.critical(
                "CANONICAL_BROKER_BOOTSTRAP_READY marker=%s broker=%s hydrated=%s "
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
                "CANONICAL_BROKER_BOOTSTRAP_REFRESH_WAITING marker=%s err=%s state=%s",
                _MARKER,
                exc,
                last,
            )
        time.sleep(poll_s)

    os.environ["NIJA_CANONICAL_BROKER_BOOTSTRAP_READY"] = "0"
    raise RuntimeError(
        "canonical broker capital hydration timed out "
        f"after {timeout_s:.1f}s state={last}"
    )


def _patch_bot_main(module: ModuleType) -> bool:
    global _ORIGINAL
    current = getattr(module, "_run_self_healing_startup", None)
    if not callable(current):
        return False
    if bool(getattr(current, _WRAP_ATTR, False)):
        return True

    _ORIGINAL = current

    def patched(*args: Any, **kwargs: Any):
        ok, broker, broker_name = current(*args, **kwargs)
        if not ok:
            return ok, broker, broker_name
        try:
            return _initialize_canonical_broker_runtime(broker, broker_name)
        except Exception as exc:
            os.environ["NIJA_CANONICAL_BROKER_BOOTSTRAP_READY"] = "0"
            logger.critical(
                "CANONICAL_BROKER_BOOTSTRAP_FAILED marker=%s broker=%s err=%s "
                "trading_remains_fail_closed=true",
                _MARKER,
                broker_name or type(broker).__name__,
                exc,
                exc_info=True,
            )
            return False, None, ""

    setattr(patched, _WRAP_ATTR, True)
    setattr(patched, "__wrapped__", current)
    setattr(module, "_run_self_healing_startup", patched)
    logger.critical(
        "CANONICAL_BROKER_BOOTSTRAP_HANDOFF_PATCHED marker=%s module=%s",
        _MARKER,
        module.__name__,
    )
    return True


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        module = importlib.import_module("bot.bot_main")
        patched = _patch_bot_main(module)
        _INSTALLED = bool(patched)
        os.environ["NIJA_CANONICAL_BROKER_BOOTSTRAP_HANDOFF_INSTALLED"] = "1" if patched else "0"
        logger.critical(
            "CANONICAL_BROKER_BOOTSTRAP_HANDOFF_INSTALLED marker=%s patched=%s",
            _MARKER,
            patched,
        )
        return patched


def install() -> bool:
    return install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_initialize_canonical_broker_runtime",
    "_patch_bot_main",
    "_manager_contract",
    "_capital_snapshot",
]
