"""Initialize the canonical broker manager before SelfHealingStartup.

The production startup path previously waited for SelfHealingStartup to return a
connected broker before initializing the canonical MultiAccountBrokerManager.
SelfHealingStartup itself delegates broker connection to that manager, creating a
circular dependency that can leave the writer process in LIVE_PENDING_CONFIRMATION
with no manager, no capital snapshot, and no scan cycles.

This module patches the canonical bot_main writer-acquisition function. After
Redis writer authority is acquired and synchronously verified, the existing
canonical manager singleton is initialized on the main bootstrap thread before
SelfHealingStartup runs. A failed prebootstrap releases only this process's own
lease and returns startup failure; no order, authority, or state gate is bypassed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.canonical_broker_prebootstrap")

_MARKER = "20260723-canonical-broker-prebootstrap-v22"
_LOCK = threading.RLock()
_READY = False
_INSTALLED = False
_ACQUIRE_WRAP_ATTR = "_nija_canonical_broker_prebootstrap_acquire_v22"
_MAIN_WRAP_ATTR = "_nija_canonical_broker_prebootstrap_main_v22"


def _canonical_manager() -> Any:
    module = importlib.import_module("bot.multi_account_broker_manager")
    manager = getattr(module, "multi_account_broker_manager", None)
    if manager is None:
        getter = getattr(module, "get_broker_manager", None)
        manager = getter() if callable(getter) else None
    if manager is None:
        raise RuntimeError("canonical MultiAccountBrokerManager singleton unavailable")
    return manager


def _manager_contract(manager: Any) -> tuple[bool, str]:
    if not bool(getattr(manager, "_fsm_initialized", False)):
        return False, "fsm_not_initialized"

    has_sources = getattr(manager, "has_registered_sources", None)
    if callable(has_sources):
        try:
            if not bool(has_sources()):
                return False, "no_registered_platform_source"
        except Exception as exc:
            return False, f"source_contract_error:{type(exc).__name__}:{exc}"

    attempted = getattr(manager, "has_attempted_connections", None)
    if callable(attempted):
        try:
            if not bool(attempted()):
                return False, "broker_registration_not_finalized"
        except Exception as exc:
            return False, f"attempt_contract_error:{type(exc).__name__}:{exc}"

    return True, "manager_ready"


def _repair_capital_fsm_latch(manager: Any, cause: BaseException) -> bool:
    if bool(getattr(manager, "_fsm_initialized", False)):
        return True

    repair = getattr(manager, "_init_capital_fsm", None)
    if not callable(repair):
        return False

    logger.critical(
        "CANONICAL_BROKER_PREBOOTSTRAP_V22_LATCH_REPAIR_BEGIN marker=%s cause=%s:%s",
        _MARKER,
        type(cause).__name__,
        cause,
    )
    repair()
    repaired = bool(getattr(manager, "_fsm_initialized", False))
    logger.critical(
        "CANONICAL_BROKER_PREBOOTSTRAP_V22_LATCH_REPAIR_RESULT marker=%s repaired=%s",
        _MARKER,
        repaired,
    )
    return repaired


def _initialize_manager(manager: Any) -> None:
    initialize = getattr(manager, "initialize", None)
    if not callable(initialize):
        raise RuntimeError("MultiAccountBrokerManager.initialize is unavailable")

    try:
        initialize()
    except Exception as first_exc:
        # Retry only the confirmed stale InitRegistry/FSM-latch case. Broker,
        # credential, balance, and network failures must remain fail-closed.
        if bool(getattr(manager, "_fsm_initialized", False)):
            raise
        if not _repair_capital_fsm_latch(manager, first_exc):
            raise
        logger.warning(
            "CANONICAL_BROKER_PREBOOTSTRAP_V22_INITIALIZE_RETRY marker=%s first_error=%s:%s",
            _MARKER,
            type(first_exc).__name__,
            first_exc,
        )
        initialize()


def _platform_counts(manager: Any) -> tuple[int, int, list[str]]:
    brokers = getattr(manager, "platform_brokers", None)
    if callable(brokers):
        brokers = brokers()
    if brokers is None:
        brokers = getattr(manager, "_platform_brokers", {})

    try:
        items = list(dict(brokers or {}).items())
    except Exception:
        items = []

    connected_names: list[str] = []
    for broker_type, broker in items:
        if broker is None or not bool(getattr(broker, "connected", False)):
            continue
        name = getattr(broker_type, "value", None) or str(broker_type)
        connected_names.append(str(name).lower())

    return len(items), len(connected_names), sorted(set(connected_names))


def prepare_canonical_broker_runtime() -> Any:
    """Synchronously prepare the canonical manager after writer verification."""

    global _READY
    with _LOCK:
        manager = _canonical_manager()
        contract_ok, _ = _manager_contract(manager)
        registered, connected, names = _platform_counts(manager)
        if _READY and contract_ok and connected >= 1:
            logger.info(
                "CANONICAL_BROKER_PREBOOTSTRAP_V22_ALREADY_READY marker=%s registered=%d connected=%d brokers=%s",
                _MARKER,
                registered,
                connected,
                ",".join(names),
            )
            return manager

        logger.critical(
            "CANONICAL_BROKER_PREBOOTSTRAP_V22_BEGIN marker=%s thread=%s",
            _MARKER,
            threading.current_thread().name,
        )
        _initialize_manager(manager)

        contract_ok, contract_reason = _manager_contract(manager)
        registered, connected, names = _platform_counts(manager)
        if not contract_ok:
            raise RuntimeError(
                f"canonical broker prebootstrap contract failed: {contract_reason}"
            )
        if connected < 1:
            raise RuntimeError(
                "canonical broker prebootstrap has no connected platform broker "
                f"(registered={registered}, connected={connected})"
            )

        _READY = True
        os.environ["NIJA_CANONICAL_BROKER_PREBOOTSTRAP_V22_READY"] = "1"
        logger.critical(
            "CANONICAL_BROKER_PREBOOTSTRAP_V22_READY marker=%s fsm_initialized=true registered=%d connected=%d brokers=%s",
            _MARKER,
            registered,
            connected,
            ",".join(names),
        )
        return manager


def _unwrap(current: Callable[..., Any]) -> Callable[..., Any]:
    seen: set[int] = set()
    base = current
    while callable(getattr(base, "__wrapped__", None)) and id(base) not in seen:
        seen.add(id(base))
        candidate = getattr(base, "__wrapped__")
        if not callable(candidate):
            break
        base = candidate
    return base


def _patch_writer_acquire(module: ModuleType) -> bool:
    current = getattr(module, "_acquire_writer_authority_before_nonce", None)
    if not callable(current):
        return False
    if bool(getattr(current, _ACQUIRE_WRAP_ATTR, False)):
        return True

    base = _unwrap(current)

    @wraps(base)
    def guarded_acquire(*args: Any, **kwargs: Any) -> bool:
        acquired = bool(base(*args, **kwargs))
        if not acquired:
            return False
        try:
            prepare_canonical_broker_runtime()
            return True
        except Exception as exc:
            os.environ["NIJA_CANONICAL_BROKER_PREBOOTSTRAP_V22_READY"] = "0"
            logger.critical(
                "CANONICAL_BROKER_PREBOOTSTRAP_V22_FAILED marker=%s err=%s:%s trading_remains_fail_closed=true",
                _MARKER,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            release = getattr(module, "_release_writer_authority", None)
            if callable(release):
                try:
                    release()
                except Exception as release_exc:
                    logger.critical(
                        "CANONICAL_BROKER_PREBOOTSTRAP_V22_RELEASE_FAILED marker=%s err=%s:%s",
                        _MARKER,
                        type(release_exc).__name__,
                        release_exc,
                        exc_info=True,
                    )
            return False

    setattr(guarded_acquire, _ACQUIRE_WRAP_ATTR, True)
    setattr(guarded_acquire, "__wrapped__", base)
    setattr(module, "_acquire_writer_authority_before_nonce", guarded_acquire)
    logger.critical(
        "CANONICAL_BROKER_PREBOOTSTRAP_V22_ACQUIRE_PATCHED marker=%s module=%s legacy_layers_unwrapped=%s",
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
        if not _patch_writer_acquire(module):
            logger.critical(
                "CANONICAL_BROKER_PREBOOTSTRAP_V22_REPATCH_FAILED marker=%s trading_remains_fail_closed=true",
                _MARKER,
            )
            return 1
        return current(*args, **kwargs)

    setattr(guarded_main, _MAIN_WRAP_ATTR, True)
    setattr(guarded_main, "__wrapped__", current)
    setattr(module, "main", guarded_main)
    logger.critical(
        "CANONICAL_BROKER_PREBOOTSTRAP_V22_MAIN_PATCHED marker=%s module=%s",
        _MARKER,
        module.__name__,
    )
    return True


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        module = importlib.import_module("bot.bot_main")
        acquire_patched = _patch_writer_acquire(module)
        main_patched = _patch_main(module)
        _INSTALLED = bool(acquire_patched and main_patched)
        os.environ["NIJA_CANONICAL_BROKER_PREBOOTSTRAP_V22_INSTALLED"] = (
            "1" if _INSTALLED else "0"
        )
        logger.critical(
            "CANONICAL_BROKER_PREBOOTSTRAP_V22_INSTALLED marker=%s acquire_patched=%s main_patched=%s",
            _MARKER,
            acquire_patched,
            main_patched,
        )
        return _INSTALLED


def install() -> bool:
    return install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "prepare_canonical_broker_runtime",
    "_canonical_manager",
    "_manager_contract",
    "_initialize_manager",
    "_platform_counts",
    "_patch_writer_acquire",
    "_patch_main",
]
