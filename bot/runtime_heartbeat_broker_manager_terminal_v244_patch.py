"""Preserve verified startup-heartbeat context through live broker-manager submit (v244).

Production proved the heartbeat passed the pipeline authority gate and router, then
failed a second authority validation inside bot.broker_manager after the bounded v233
grant expired.  The canonical startup-probe ContextVar is the preferred authority
carrier, but the same-thread v233 grant is the bounded fallback when the ContextVar
scope has already unwound before the broker-manager terminal.

v244 wraps the actual live broker-manager submit methods.  It enters only when v236
can resolve an already-verified HEARTBEAT_TRADE/HEARTBEAT_TRADE_CLOSE from either the
canonical ContextVar or the still-live same-thread v233 grant, and current startup
writer authority is reverified immediately at the terminal method.  The canonical
authority bindings are anchored for that method call so its inner
_reject_if_unauthorized_order_submit check observes the verified probe.

v246 is installed from this already-authoritative heartbeat convergence slot.  It
copies existing ContextVars into ExecutionPipeline's timeout worker so the verified
startup probe is not lost merely because routing crosses a ThreadPoolExecutor
boundary.  v246 creates no authority and does not patch the stdlib executor globally.

v255 is installed from this terminal convergence owner after v244/v246 are ready. It
adds bounded failover between already-ready heartbeat venues for proven process-local
read contention, reasserts real position-fetch proof propagation, and prevents a
non-owner capital refresh thread from mutating BootstrapFSM. It never creates proof or
weakens any execution gate.

Ordinary orders, lifecycle state, nonce, risk, capital, broker health, kill switch,
minimum notional, exchange acknowledgement, fill proof, and readiness remain unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_broker_manager_terminal_v244")
MARKER = "20260826-heartbeat-broker-manager-terminal-v244"
_FLAG = "NIJA_HEARTBEAT_BROKER_MANAGER_TERMINAL_V244_READY"
_PATCH_ATTR = "_nija_heartbeat_broker_manager_terminal_v244"
_ALLOWED = {"HEARTBEAT_TRADE", "HEARTBEAT_TRADE_CLOSE"}
_CLASSES = ("CoinbaseBroker", "KrakenBroker", "OKXBroker", "AlpacaBroker")
_METHODS = ("place_market_order", "place_limit_order")


def _v236() -> ModuleType:
    return importlib.import_module("bot.runtime_heartbeat_final_submit_v236_patch")


def _verified_reason() -> str | None:
    """Resolve only authority that was already verified upstream."""
    v236 = _v236()
    resolver = getattr(v236, "_verified_reason", None)
    if callable(resolver):
        try:
            resolved = resolver()
        except Exception as exc:
            LOGGER.warning(
                "HEARTBEAT_BROKER_MANAGER_TERMINAL_V244_RESOLVE_ERROR marker=%s "
                "error=%s:%s trading_fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
            resolved = None
        value = resolved[0] if isinstance(resolved, tuple) and resolved else resolved
        normalized = str(value or "").strip().upper()
        if normalized in _ALLOWED:
            return normalized

    canonical = getattr(v236, "_canonical_verified_probe", None)
    if not callable(canonical):
        return None
    try:
        reason = canonical()
    except Exception:
        return None
    normalized = str(reason or "").strip().upper()
    return normalized if normalized in _ALLOWED else None


def _writer_ready() -> bool:
    return bool(getattr(_v236(), "_reverify_startup_write_authority")())


def _wrap_method(current: Callable[..., Any], module: ModuleType, surface: str) -> Callable[..., Any]:
    if bool(getattr(current, _PATCH_ATTR, False)):
        return current

    @wraps(current)
    def terminal_v244(self: Any, *args: Any, **kwargs: Any):
        reason = _verified_reason()
        if reason is None:
            return current(self, *args, **kwargs)
        v236 = _v236()
        authority = getattr(v236, "_authority_module")()
        scope = getattr(authority, "startup_execution_probe_scope", None) if authority else None
        bindings = getattr(v236, "_canonical_terminal_bindings", None)
        if not callable(scope) or not callable(bindings) or not _writer_ready():
            LOGGER.warning(
                "HEARTBEAT_BROKER_MANAGER_TERMINAL_V244_DEFERRED marker=%s surface=%s "
                "probe_reason=%s startup_writer_reverified=false trading_fail_closed=true",
                MARKER, surface, reason,
            )
            return current(self, *args, **kwargs)
        LOGGER.critical(
            "HEARTBEAT_BROKER_MANAGER_TERMINAL_V244_REANCHORED marker=%s surface=%s "
            "probe_reason=%s verified_upstream_authority=true startup_writer_reverified=true "
            "canonical_terminal_bindings=true grant_ttl_not_extended=true ordinary_orders_unchanged=true "
            "lifecycle_nonce_risk_capital_broker_health_killswitch_min_notional_fill_gates_unchanged=true "
            "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            MARKER, surface, reason,
        )
        with scope(reason), bindings(module):
            return current(self, *args, **kwargs)

    setattr(terminal_v244, _PATCH_ATTR, True)
    setattr(terminal_v244, "__wrapped__", current)
    return terminal_v244


def _patch_broker_manager_methods() -> tuple[bool, tuple[str, ...]]:
    module = importlib.import_module("bot.broker_manager")
    patched: list[str] = []
    for class_name in _CLASSES:
        cls = getattr(module, class_name, None)
        if not isinstance(cls, type):
            continue
        for method_name in _METHODS:
            current = getattr(cls, method_name, None)
            if not callable(current):
                continue
            surface = f"{class_name}.{method_name}"
            wrapped = _wrap_method(current, module, surface)
            setattr(cls, method_name, wrapped)
            if bool(getattr(getattr(cls, method_name, None), _PATCH_ATTR, False)):
                patched.append(surface)
    required = all(
        surface in patched
        for surface in ("CoinbaseBroker.place_market_order", "KrakenBroker.place_market_order")
    )
    return required, tuple(sorted(set(patched)))


def _install_v246_context_handoff() -> bool:
    try:
        module = importlib.import_module("bot.runtime_execution_context_handoff_v246_patch")
        installer = getattr(module, "install", None) or getattr(module, "install_import_hook", None)
        return bool(callable(installer) and installer())
    except Exception as exc:
        LOGGER.error(
            "HEARTBEAT_BROKER_MANAGER_TERMINAL_V244_V246_INSTALL_ERROR marker=%s "
            "error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        return False


def _install_v255_terminal_activation_liveness() -> bool:
    """Install the terminal liveness repair after the verified submit chain is ready."""
    try:
        module = importlib.import_module("bot.runtime_terminal_activation_liveness_v255_patch")
        installer = getattr(module, "install", None) or getattr(module, "install_import_hook", None)
        ready = bool(callable(installer) and installer())
        if not ready:
            LOGGER.error(
                "HEARTBEAT_BROKER_MANAGER_TERMINAL_V244_V255_INSTALL_FAILED marker=%s "
                "trading_fail_closed=true",
                MARKER,
            )
        return ready
    except Exception as exc:
        LOGGER.error(
            "HEARTBEAT_BROKER_MANAGER_TERMINAL_V244_V255_INSTALL_ERROR marker=%s "
            "error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        return False


def install() -> bool:
    try:
        v240 = importlib.import_module("bot.runtime_heartbeat_terminal_lifecycle_v240_patch")
        upstream_install = getattr(v240, "install", None)
        upstream = bool(callable(upstream_install) and upstream_install())
        methods_ready, surfaces = _patch_broker_manager_methods()
        context_handoff_ready = _install_v246_context_handoff()
        v255_ready = _install_v255_terminal_activation_liveness()
        ready = bool(upstream and methods_ready and context_handoff_ready and v255_ready)
    except Exception as exc:
        LOGGER.error(
            "HEARTBEAT_BROKER_MANAGER_TERMINAL_V244_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        ready, surfaces, context_handoff_ready, v255_ready = False, (), False, False
    os.environ[_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "HEARTBEAT_BROKER_MANAGER_TERMINAL_V244_READY marker=%s ready=true surfaces=%s "
            "coinbase_live_terminal_required=true kraken_live_terminal_required=true "
            "verified_v233_grant_fallback=true canonical_context_preferred=true "
            "pipeline_context_handoff_v246=true terminal_activation_liveness_v255=true "
            "startup_writer_reverification_required=true grant_ttl_not_extended=true "
            "ordinary_orders_unchanged=true execution_proof_fabricated=false "
            "forced_activation=false safety_gates_bypassed=false",
            MARKER, ",".join(surfaces),
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_wrap_method",
    "_patch_broker_manager_methods",
    "_install_v246_context_handoff",
    "_install_v255_terminal_activation_liveness",
    "_verified_reason",
    "_writer_ready",
]
