"""Final runtime convergence for account routing, exit ownership, and adoption.

This patch is deliberately narrow: it does not grant execution authority, bypass
broker authentication, or relax risk controls. It repairs four runtime contracts:

* OKX readiness is not complete until the execution router itself is patched.
* Exactly one exit-only worker may own an account/broker identity per process.
* Independent user accounts retain ``user_mode=True``; copy-trading being disabled
  must not convert a user account into platform mode.
* Held-position adoption performs exchange synchronization and cost-basis verification
  before any automated exit cycle can run.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.final_account_router_exit_convergence")
_MARKER = "20260718-final-account-router-exit-v2"
_LOCK = threading.RLock()
_INSTALLED = False
_EXIT_REGISTRY_LOCK = threading.RLock()
_EXIT_REGISTRY: dict[str, threading.Thread] = {}


def _patch_okx_router() -> bool:
    bridge = importlib.import_module("bot.okx_final_order_submission_bridge_patch")
    router = importlib.import_module("bot.multi_broker_execution_router")
    patch_router = getattr(bridge, "_patch_router_module", None)
    if callable(patch_router):
        patch_router(router)
    ready = bool(getattr(bridge, "_ROUTER_PATCHED", False))
    if not ready:
        logger.error("OKX_ROUTER_BIND_PENDING marker=%s router_module=%s", _MARKER, router.__name__)
        return False
    os.environ["NIJA_OKX_ROUTER_PATCHED"] = "1"
    logger.critical("OKX_ROUTER_BIND_VERIFIED marker=%s router_patched=true", _MARKER)
    return True


def _patch_venue_readiness() -> bool:
    module = importlib.import_module("venue_readiness_execution_repair_patch")
    current = getattr(module, "_bind_okx_bridge_once", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_require_okx_router_v2", False):
        return _patch_okx_router()

    @wraps(current)
    def bind() -> bool:
        current()
        return _patch_okx_router()

    bind._nija_require_okx_router_v2 = True  # type: ignore[attr-defined]
    bind.__wrapped__ = current  # type: ignore[attr-defined]
    module._bind_okx_bridge_once = bind
    return bind()


def _thread_alive(thread: Any) -> bool:
    return bool(thread is not None and callable(getattr(thread, "is_alive", None)) and thread.is_alive())


def _patch_exit_worker_ownership() -> bool:
    module = importlib.import_module("account_exit_management_recovery_patch")
    current = getattr(module, "_ensure_exit_thread", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_global_exit_owner_v2", False):
        return True

    @wraps(current)
    def ensure(trader: Any, identity: str, scope: str, user_id: Any, broker_type: Any, broker: Any) -> bool:
        name = f"ExitManager-{str(identity).replace(':', '-')}"
        with _EXIT_REGISTRY_LOCK:
            registered = _EXIT_REGISTRY.get(identity)
            if _thread_alive(registered):
                return False
            for thread in threading.enumerate():
                if thread.name == name and thread.is_alive():
                    _EXIT_REGISTRY[identity] = thread
                    logger.warning("DUPLICATE_EXIT_WORKER_SUPPRESSED marker=%s account=%s owner=%s", _MARKER, identity, thread.ident)
                    return False
            created = bool(current(trader, identity, scope, user_id, broker_type, broker))
            thread = (getattr(trader, "_nija_exit_recovery_threads", {}) or {}).get(identity)
            if created and _thread_alive(thread):
                _EXIT_REGISTRY[identity] = thread
                logger.critical("ACCOUNT_EXIT_WORKER_SINGLETON_ACQUIRED marker=%s account=%s thread=%s", _MARKER, identity, thread.ident)
            return created

    ensure._nija_global_exit_owner_v2 = True  # type: ignore[attr-defined]
    ensure.__wrapped__ = current  # type: ignore[attr-defined]
    module._ensure_exit_thread = ensure
    return True


def _patch_user_mode() -> bool:
    module = importlib.import_module("bot.trade_cycle_convergence_repair_patch")
    current = getattr(module, "_truthy", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_user_mode_truth_v2", False):
        return True

    @wraps(current)
    def truthy(name: str, default: bool = False) -> bool:
        # Prevent the inverted legacy branch in cycle convergence from demoting
        # an independent user account to platform mode.
        if name == "NIJA_INDEPENDENT_USER_TRADING":
            return False
        return bool(current(name, default))

    truthy._nija_user_mode_truth_v2 = True  # type: ignore[attr-defined]
    truthy.__wrapped__ = current  # type: ignore[attr-defined]
    module._truthy = truthy
    os.environ["NIJA_USER_MODE_CONVERGENCE_INSTALLED"] = "1"
    logger.critical("INDEPENDENT_USER_MODE_PRESERVED marker=%s user_mode_effective=true", _MARKER)
    return True


def _patch_adoption_sync() -> bool:
    module = importlib.import_module("account_exit_management_recovery_patch")
    current = getattr(module, "_adopt_and_manage", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_verified_adoption_sync_v2", False):
        return True

    @wraps(current)
    def adopt_and_manage(trader: Any, identity: str, broker: Any):
        strategy = getattr(trader, "trading_strategy", None)
        if strategy is None:
            return current(trader, identity, broker)

        try:
            setattr(strategy, "broker", broker)
            sync = importlib.import_module("bot.startup_position_sync")
            sync_fn = getattr(sync, "sync_exchange_positions_on_startup", None)
            if callable(sync_fn):
                sync_fn(strategy)
        except Exception as exc:
            logger.warning("PRE_ADOPTION_POSITION_SYNC_FAILED marker=%s account=%s error=%s", _MARKER, identity, exc)

        original_run_cycle = getattr(strategy, "run_cycle", None)
        deferred_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        def defer_cycle(*args: Any, **kwargs: Any) -> int:
            deferred_calls.append((args, kwargs))
            logger.info("POSITION_EXIT_CYCLE_DEFERRED marker=%s account=%s reason=awaiting_cost_basis_verification", _MARKER, identity)
            return 0

        if callable(original_run_cycle):
            strategy.run_cycle = defer_cycle
        try:
            result = current(trader, identity, broker)
        finally:
            if callable(original_run_cycle):
                strategy.run_cycle = original_run_cycle

        verifier = getattr(strategy, "verify_position_adoption_status", None)
        verified = False
        if callable(verifier):
            try:
                verified = bool(verifier(
                    broker=broker,
                    broker_name=identity,
                    account_id=identity.upper().replace(':', '_'),
                ))
            except Exception as exc:
                logger.warning("POSITION_COST_BASIS_VERIFY_FAILED marker=%s account=%s error=%s", _MARKER, identity, exc)

        if not verified:
            logger.error("UNVERIFIED_POSITION_EXIT_CYCLE_BLOCKED marker=%s account=%s deferred_cycles=%d", _MARKER, identity, len(deferred_calls))
            return result

        logger.critical("POSITION_COST_BASIS_VERIFIED_BEFORE_EXIT marker=%s account=%s deferred_cycles=%d", _MARKER, identity, len(deferred_calls))
        if callable(original_run_cycle):
            for args, kwargs in deferred_calls[:1]:
                original_run_cycle(*args, **kwargs)
        return result

    adopt_and_manage._nija_verified_adoption_sync_v2 = True  # type: ignore[attr-defined]
    adopt_and_manage.__wrapped__ = current  # type: ignore[attr-defined]
    module._adopt_and_manage = adopt_and_manage
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        results = {
            "okx_router": _patch_venue_readiness(),
            "exit_singleton": _patch_exit_worker_ownership(),
            "user_mode": _patch_user_mode(),
            "adoption_sync": _patch_adoption_sync(),
        }
        if not all(results.values()):
            raise RuntimeError(f"final_account_router_exit_convergence_incomplete:{results}")
        _INSTALLED = True
        os.environ["NIJA_FINAL_ACCOUNT_ROUTER_EXIT_CONVERGENCE_INSTALLED"] = "1"
        logger.critical("FINAL_ACCOUNT_ROUTER_EXIT_CONVERGENCE_READY marker=%s results=%s", _MARKER, results)
        return True


__all__ = ["install", "_patch_okx_router", "_patch_exit_worker_ownership", "_patch_user_mode", "_patch_adoption_sync"]
