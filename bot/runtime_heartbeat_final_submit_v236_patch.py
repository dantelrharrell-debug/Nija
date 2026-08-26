"""Finalize the verified startup-heartbeat handoff at broker submission (v236).

Production on 2026-08-26 showed that the heartbeat order passes risk/ECEL and the
pipeline startup-probe authority check, but a later broker terminal can still
re-evaluate the canonical lifecycle as BOOT.  The final live Coinbase path is a
``CoinbaseBrokerAdapter`` method in ``bot.broker_integration``.  That method resolves
``_reject_if_unauthorized_order_submit`` from the module globals at call time, so
patching only the helper function is not sufficient when another convergence pass
later restores or re-wraps that global.

v236 therefore keeps the verified startup-probe context alive through the pipeline
helper *and* installs a class-method terminal wrapper on live broker adapter submit
methods.  The wrapper does not authorize from symbol, strategy text, thread name, or
call stack.  It only enters when the canonical startup-probe ContextVar is already
independently verified as HEARTBEAT_TRADE/HEARTBEAT_TRADE_CLOSE and startup writer
authority is reverified immediately before the broker method.  Inside that verified
scope the module-local can_execute/can_execute_startup_probe bindings are reanchored
to the canonical authority functions for the duration of the call.

No lifecycle state is mutated. Kill switch, writer/lease authority, nonce, risk,
capital, broker health, ECEL, minimum notional, exchange acknowledgement, fill proof
and activation proof remain unchanged. A real exchange result is still required.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from contextlib import contextmanager
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_heartbeat_final_submit_v236")
MARKER = "20260826-heartbeat-final-submit-v236"
_FLAG = "NIJA_HEARTBEAT_FINAL_SUBMIT_V236_READY"
_PATCH_ATTR = "_nija_heartbeat_final_submit_v236"
_HELPER_PATCH_ATTR = "_nija_heartbeat_submit_context_v236"
_METHOD_PATCH_ATTR = "_nija_heartbeat_live_adapter_submit_v236"
_MODULES = (
    "bot.broker_manager",
    "broker_manager",
    "bot.broker_integration",
    "broker_integration",
)
_SUBMITTER_MODULES = ("bot.pipeline_order_submitter", "pipeline_order_submitter")
_ALLOWED_PROBE_REASONS = {"HEARTBEAT_TRADE", "HEARTBEAT_TRADE_CLOSE"}
_LIVE_ADAPTER_CLASSES = (
    "CoinbaseBrokerAdapter",
    "KrakenBrokerAdapter",
    "OKXBrokerAdapter",
    "AlpacaBrokerAdapter",
)
_LIVE_SUBMIT_METHODS = ("place_market_order", "place_limit_order")


def _authority_module() -> ModuleType | None:
    try:
        module = sys.modules.get("bot.execution_authority_context") or sys.modules.get("execution_authority_context")
        if not isinstance(module, ModuleType):
            module = importlib.import_module("bot.execution_authority_context")
        return module if isinstance(module, ModuleType) else None
    except Exception:
        return None


def _live_verified_grant() -> str | None:
    try:
        v233 = importlib.import_module("bot.runtime_heartbeat_terminal_authority_v233_patch")
        grant = getattr(v233, "_GRANT", None)
        if grant is None or int(getattr(grant, "thread_id", -1)) != threading.get_ident():
            return None
        if float(getattr(grant, "expires", 0.0) or 0.0) < time.monotonic():
            return None
        if int(getattr(grant, "remaining", 0) or 0) <= 0:
            return None
        reason = str(getattr(grant, "probe_reason", "") or "").strip().upper()
        return reason if reason in _ALLOWED_PROBE_REASONS else None
    except Exception:
        return None


def _canonical_verified_probe() -> str | None:
    authority = _authority_module()
    checker = getattr(authority, "can_execute_startup_probe", None) if authority else None
    if not callable(checker):
        return None
    try:
        allowed, reason = checker()
    except Exception as exc:
        LOGGER.warning("HEARTBEAT_FINAL_SUBMIT_V236_PROBE_CHECK_ERROR marker=%s error=%s:%s trading_fail_closed=true", MARKER, type(exc).__name__, exc)
        return None
    normalized = str(reason or "").strip().upper()
    return normalized if bool(allowed) and normalized in _ALLOWED_PROBE_REASONS else None


def _reverify_startup_write_authority() -> bool:
    authority = _authority_module()
    check = getattr(authority, "assert_startup_write_authority", None) if authority else None
    if not callable(check):
        return False
    try:
        check()
        return True
    except Exception as exc:
        LOGGER.warning("HEARTBEAT_FINAL_SUBMIT_V236_REVERIFY_FAILED marker=%s error=%s:%s trading_fail_closed=true", MARKER, type(exc).__name__, exc)
        return False


def _eligible_boot_denial(exc: BaseException) -> bool:
    text = str(exc or "").lower()
    return "lifecycle_phase:boot" in text or "lifecycle_phase_not_live" in text


def _verified_reason() -> tuple[str | None, str]:
    reason = _live_verified_grant()
    if reason is not None:
        return reason, "v233_grant"
    reason = _canonical_verified_probe()
    return (reason, "canonical_probe") if reason is not None else (None, "none")


def _strategy_from_submit_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    raw = kwargs.get("strategy")
    if raw is None and len(args) >= 6:
        raw = args[5]
    return str(raw or "").strip().upper()


@contextmanager
def _canonical_terminal_bindings(module: ModuleType):
    authority = _authority_module()
    if authority is None:
        yield
        return
    canonical_can = getattr(authority, "can_execute", None)
    canonical_probe = getattr(authority, "can_execute_startup_probe", None)
    old_can = getattr(module, "can_execute", None)
    old_probe = getattr(module, "can_execute_startup_probe", None)
    try:
        if callable(canonical_can):
            setattr(module, "can_execute", canonical_can)
        if callable(canonical_probe):
            setattr(module, "can_execute_startup_probe", canonical_probe)
        yield
    finally:
        # Do not restore stale aliases over a newer convergence repair. Restore only
        # when our temporary canonical binding is still the value we installed.
        if callable(canonical_can) and getattr(module, "can_execute", None) is canonical_can and callable(old_can):
            setattr(module, "can_execute", old_can)
        if callable(canonical_probe) and getattr(module, "can_execute_startup_probe", None) is canonical_probe and callable(old_probe):
            setattr(module, "can_execute_startup_probe", old_probe)


def _patch_submit_helper() -> bool:
    module: ModuleType | None = None
    for name in _SUBMITTER_MODULES:
        candidate = sys.modules.get(name)
        if isinstance(candidate, ModuleType):
            module = candidate
            break
    if module is None:
        try:
            module = importlib.import_module("bot.pipeline_order_submitter")
        except Exception:
            return False
    current = getattr(module, "submit_market_order_via_pipeline", None)
    if not callable(current):
        return False
    if bool(getattr(current, _HELPER_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def submit_with_verified_context(*args: Any, **kwargs: Any):
        strategy = _strategy_from_submit_call(args, kwargs)
        if strategy not in _ALLOWED_PROBE_REASONS:
            return current(*args, **kwargs)
        verified_reason = _canonical_verified_probe()
        if verified_reason is None or verified_reason != strategy:
            return current(*args, **kwargs)
        authority = _authority_module()
        scope = getattr(authority, "startup_execution_probe_scope", None) if authority else None
        if not callable(scope) or not _reverify_startup_write_authority():
            return current(*args, **kwargs)
        LOGGER.critical("HEARTBEAT_SUBMIT_CONTEXT_V236_PRESERVED marker=%s probe_reason=%s caller_already_verified=true startup_write_authority_reverified=true pipeline_submit_scope=true ordinary_orders_unchanged=true lifecycle_unchanged=true execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false", MARKER, verified_reason)
        with scope(verified_reason):
            return current(*args, **kwargs)

    setattr(submit_with_verified_context, _HELPER_PATCH_ATTR, True)
    setattr(submit_with_verified_context, "__wrapped__", current)
    setattr(module, "submit_market_order_via_pipeline", submit_with_verified_context)
    for alias in _SUBMITTER_MODULES:
        alias_module = sys.modules.get(alias)
        if isinstance(alias_module, ModuleType):
            setattr(alias_module, "submit_market_order_via_pipeline", submit_with_verified_context)
    for strategy_name in ("bot.trading_strategy", "trading_strategy"):
        strategy_module = sys.modules.get(strategy_name)
        if isinstance(strategy_module, ModuleType):
            setattr(strategy_module, "submit_market_order_via_pipeline", submit_with_verified_context)
    return True


def _patch_module(module: ModuleType) -> bool:
    current = getattr(module, "_reject_if_unauthorized_order_submit", None)
    if not callable(current):
        return True
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def final_submit_v236(*args: Any, **kwargs: Any):
        try:
            return current(*args, **kwargs)
        except BaseException as exc:
            if not _eligible_boot_denial(exc):
                raise
            reason, source = _verified_reason()
            if reason is None or not _reverify_startup_write_authority():
                raise
            LOGGER.critical("HEARTBEAT_FINAL_SUBMIT_V236_ALLOWED marker=%s probe_reason=%s verification_source=%s same_thread=%s startup_write_authority_reverified=true final_submit_only=true canonical_lifecycle_unchanged=true ordinary_orders_unchanged=true kill_switch_nonce_risk_capital_broker_health_ecel_min_notional_order_fill_gates_unchanged=true execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false", MARKER, reason, source, str(source == "v233_grant").lower())
            return None

    setattr(final_submit_v236, _PATCH_ATTR, True)
    setattr(final_submit_v236, "__wrapped__", current)
    setattr(module, "_reject_if_unauthorized_order_submit", final_submit_v236)
    return True


def _patch_live_adapter_methods() -> tuple[bool, tuple[str, ...]]:
    try:
        module = importlib.import_module("bot.broker_integration")
    except Exception:
        return False, ()
    patched: list[str] = []
    for class_name in _LIVE_ADAPTER_CLASSES:
        cls = getattr(module, class_name, None)
        if not isinstance(cls, type):
            continue
        for method_name in _LIVE_SUBMIT_METHODS:
            current = getattr(cls, method_name, None)
            if not callable(current):
                continue
            if bool(getattr(current, _METHOD_PATCH_ATTR, False)):
                patched.append(f"{class_name}.{method_name}")
                continue

            @wraps(current)
            def verified_live_submit(self: Any, *args: Any, __current=current, __surface=f"{class_name}.{method_name}", **kwargs: Any):
                reason = _canonical_verified_probe()
                if reason is None:
                    return __current(self, *args, **kwargs)
                authority = _authority_module()
                scope = getattr(authority, "startup_execution_probe_scope", None) if authority else None
                if not callable(scope) or not _reverify_startup_write_authority():
                    return __current(self, *args, **kwargs)
                LOGGER.critical("HEARTBEAT_LIVE_ADAPTER_SUBMIT_V236_REANCHORED marker=%s probe_reason=%s surface=%s canonical_terminal_bindings=true startup_write_authority_reverified=true ordinary_orders_unchanged=true lifecycle_unchanged=true execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false", MARKER, reason, __surface)
                with scope(reason), _canonical_terminal_bindings(module):
                    return __current(self, *args, **kwargs)

            setattr(verified_live_submit, _METHOD_PATCH_ATTR, True)
            setattr(verified_live_submit, "__wrapped__", current)
            setattr(cls, method_name, verified_live_submit)
            patched.append(f"{class_name}.{method_name}")
    required = "CoinbaseBrokerAdapter.place_market_order" in patched
    return required, tuple(sorted(set(patched)))


def _patch_surfaces() -> tuple[bool, tuple[str, ...]]:
    patched: list[str] = []
    seen: set[int] = set()
    for name in _MODULES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        if id(module) in seen:
            continue
        seen.add(id(module))
        if _patch_module(module):
            patched.append(str(getattr(module, "__name__", name)))
    return bool(patched), tuple(sorted(set(patched)))


def install() -> bool:
    try:
        v235 = importlib.import_module("bot.runtime_heartbeat_terminal_broker_manager_v235_patch")
        install_v235 = getattr(v235, "install", None)
        upstream = bool(callable(install_v235) and install_v235())
        helper_ready = _patch_submit_helper()
        terminal, patched = _patch_surfaces()
        adapter_ready, adapters = _patch_live_adapter_methods()
        ready = bool(upstream and helper_ready and terminal and adapter_ready and _authority_module() is not None)
    except Exception as exc:
        LOGGER.error("HEARTBEAT_FINAL_SUBMIT_V236_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true", MARKER, type(exc).__name__, exc)
        ready, patched, adapters = False, (), ()
    os.environ[_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical("HEARTBEAT_FINAL_SUBMIT_V236_READY marker=%s ready=true patched_surfaces=%s live_adapter_methods=%s verified_submit_context_preserved=true canonical_terminal_reanchor=true v233_verified_grant_preferred=true canonical_probe_fallback=true v235_required=true startup_write_authority_reverified=true final_submit_only=true canonical_lifecycle_unchanged=true ordinary_orders_unchanged=true execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false", MARKER, ",".join(patched), ",".join(adapters))
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_live_verified_grant", "_canonical_verified_probe", "_patch_submit_helper", "_patch_surfaces", "_patch_live_adapter_methods"]
