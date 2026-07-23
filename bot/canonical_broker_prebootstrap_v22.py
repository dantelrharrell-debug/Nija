"""Initialize the canonical broker manager before SelfHealingStartup.

The production startup path previously waited for SelfHealingStartup to return a
connected broker before initializing the canonical MultiAccountBrokerManager.
SelfHealingStartup itself delegates broker connection to that manager, creating a
circular dependency that can leave the writer process in LIVE_PENDING_CONFIRMATION
with no manager, no capital snapshot, and no scan cycles.

This module is called synchronously by bot_main only after distributed writer
authority has been acquired and verified. It initializes the existing canonical
manager singleton, repairs only that singleton's missing capital-FSM latch when an
earlier InitRegistry claimant left it unwired, and requires at least one connected
platform broker before startup may continue.
"""
from __future__ import annotations

import importlib
import logging
import threading
from typing import Any

logger = logging.getLogger("nija.canonical_broker_prebootstrap")

_MARKER = "20260723-canonical-broker-prebootstrap-v22"
_LOCK = threading.RLock()
_READY = False


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
        logger.critical(
            "CANONICAL_BROKER_PREBOOTSTRAP_V22_READY marker=%s fsm_initialized=true registered=%d connected=%d brokers=%s",
            _MARKER,
            registered,
            connected,
            ",".join(names),
        )
        return manager


__all__ = [
    "prepare_canonical_broker_runtime",
    "_canonical_manager",
    "_manager_contract",
    "_initialize_manager",
    "_platform_counts",
]
