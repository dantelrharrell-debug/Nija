"""Re-arm heartbeat verification when an existing strategy is republished (v203).

Production startup can create a ``TradingStrategy`` before the final canonical
broker set is hydrated. ``strategy_publication_patch`` later reuses that same
object and repairs its brokers/symbols instead of calling ``TradingStrategy``
``__init__`` again. The constructor is the normal owner of heartbeat scheduling,
so a reused instance can reach RUNNING_SUPERVISED with every structural gate
ready while no heartbeat verifier thread exists to create the required genuine
execution proof.

This patch repairs scheduling liveness only:
* it runs only when the existing HEARTBEAT_TRADE policy is enabled,
* it never writes heartbeat/execution proof itself,
* it never marks readiness or grants execution authority,
* it calls the existing ``_schedule_heartbeat_trade`` implementation,
* that implementation still traverses writer/nonce/risk/kill-switch,
  reconciliation, capital, min-notional, order and fill gates,
* duplicate live heartbeat threads remain blocked by the strategy's own lock.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.runtime_existing_strategy_heartbeat_rearm_v203")
MARKER = "20260823-existing-strategy-heartbeat-rearm-v203"
_READY_FLAG = "NIJA_EXISTING_STRATEGY_HEARTBEAT_REARM_V203_READY"
_PATCH_ATTR = "_nija_existing_strategy_heartbeat_rearm_v203"
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUTHY


def _thread_alive(strategy: Any) -> bool:
    thread = getattr(strategy, "_heartbeat_trade_thread", None)
    return bool(thread is not None and callable(getattr(thread, "is_alive", None)) and thread.is_alive())


def _ensure_heartbeat_scheduler(strategy: Any) -> bool:
    """Ensure the existing live strategy owns an active heartbeat verifier."""
    if strategy is None:
        return False

    if not _truthy("HEARTBEAT_TRADE"):
        LOGGER.info(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_SKIPPED marker=%s reason=policy_disabled",
            MARKER,
        )
        return True

    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        LOGGER.info(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_SKIPPED marker=%s reason=simulation_mode",
            MARKER,
        )
        return True

    if bool(getattr(strategy, "_heartbeat_trade_success", False)) and bool(
        getattr(strategy, "_heartbeat_trade_completed", False)
    ):
        LOGGER.info(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_SKIPPED marker=%s reason=already_verified",
            MARKER,
        )
        return True

    if _thread_alive(strategy):
        LOGGER.info(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_SKIPPED marker=%s reason=thread_alive",
            MARKER,
        )
        return True

    scheduler = getattr(strategy, "_schedule_heartbeat_trade", None)
    if not callable(scheduler):
        LOGGER.critical(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_FAILED marker=%s reason=scheduler_missing "
            "execution_authority_granted=false proof_fabricated=false trading_fail_closed=true",
            MARKER,
        )
        return False

    # Early-created/legacy strategy objects may have cached the policy before
    # v200/v201 aligned the live runtime environment. Refresh only that cached
    # scheduler flag; no readiness or authority state is touched here.
    setattr(strategy, "_heartbeat_trade_enabled", True)
    if getattr(strategy, "_heartbeat_trade_lock", None) is None:
        setattr(strategy, "_heartbeat_trade_lock", threading.Lock())
    if not hasattr(strategy, "_heartbeat_trade_thread"):
        setattr(strategy, "_heartbeat_trade_thread", None)
    if not hasattr(strategy, "_heartbeat_trade_completed"):
        setattr(strategy, "_heartbeat_trade_completed", False)
    if not hasattr(strategy, "_heartbeat_trade_success"):
        setattr(strategy, "_heartbeat_trade_success", False)

    try:
        scheduler()
    except Exception as exc:
        LOGGER.critical(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_FAILED marker=%s reason=scheduler_exception "
            "error=%s:%s execution_authority_granted=false proof_fabricated=false trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    alive = _thread_alive(strategy)
    LOGGER.critical(
        "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_TRIGGERED marker=%s thread_alive=%s "
        "policy_refreshed=true existing_scheduler_only=true execution_authority_granted=false "
        "proof_fabricated=false writer_nonce_risk_killswitch_reconciliation_capital_order_fill_gates_unchanged=true "
        "forced_activation=false safety_gates_bypassed=false",
        MARKER,
        str(alive).lower(),
    )
    return alive


def install() -> bool:
    """Wrap canonical strategy publication with idempotent heartbeat re-arming."""
    with _LOCK:
        try:
            module = importlib.import_module("bot.strategy_publication_patch")
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.critical(
                "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_INSTALL_FAILED marker=%s reason=publication_import_failed "
                "error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False

        current = getattr(module, "_publish", None)
        if not callable(current):
            os.environ[_READY_FLAG] = "0"
            LOGGER.critical(
                "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_INSTALL_FAILED marker=%s reason=publish_missing "
                "trading_fail_closed=true",
                MARKER,
            )
            return False

        if not getattr(current, _PATCH_ATTR, False):
            previous = current

            def _publish_with_heartbeat_rearm(strategy: Any) -> Any:
                result = previous(strategy)
                _ensure_heartbeat_scheduler(strategy)
                return result

            setattr(_publish_with_heartbeat_rearm, _PATCH_ATTR, True)
            setattr(module, "_nija_v203_previous_publish", previous)
            setattr(module, "_publish", _publish_with_heartbeat_rearm)

        installed = getattr(module, "_publish", None)
        ready = bool(callable(installed) and getattr(installed, _PATCH_ATTR, False))
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_INSTALL_FAILED marker=%s reason=wrapper_not_installed "
                "trading_fail_closed=true",
                MARKER,
            )
            return False

        LOGGER.critical(
            "EXISTING_STRATEGY_HEARTBEAT_REARM_V203_READY marker=%s ready=true "
            "existing_strategy_only=true existing_scheduler_only=true execution_authority_granted=false "
            "proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_ensure_heartbeat_scheduler"]
