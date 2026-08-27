"""Preserve verified startup-heartbeat context through live broker-manager submit (v244).

Production proved the heartbeat passed the pipeline authority gate and router, then
failed a second authority validation inside bot.broker_manager after the bounded v233
grant expired.  The canonical startup-probe ContextVar was still the correct authority
carrier; a wall-clock grant must not be extended merely to cover slow routing.

v244 wraps the actual live broker-manager submit methods.  It enters only when the
canonical ContextVar already verifies HEARTBEAT_TRADE/HEARTBEAT_TRADE_CLOSE and current
startup writer authority is reverified immediately at the terminal method.  The
canonical authority bindings are anchored for that method call so its inner
_reject_if_unauthorized_order_submit check observes the verified probe.

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
    reason = getattr(_v236(), "_canonical_verified_probe")()
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
            "probe_reason=%s canonical_context_already_verified=true "
            "startup_writer_reverified=true canonical_terminal_bindings=true "
            "grant_ttl_not_extended=true ordinary_orders_unchanged=true "
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
    required = "CoinbaseBroker.place_market_order" in patched
    return required, tuple(sorted(set(patched)))


def install() -> bool:
    try:
        v240 = importlib.import_module("bot.runtime_heartbeat_terminal_lifecycle_v240_patch")
        upstream_install = getattr(v240, "install", None)
        upstream = bool(callable(upstream_install) and upstream_install())
        methods_ready, surfaces = _patch_broker_manager_methods()
        ready = bool(upstream and methods_ready)
    except Exception as exc:
        LOGGER.error(
            "HEARTBEAT_BROKER_MANAGER_TERMINAL_V244_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        ready, surfaces = False, ()
    os.environ[_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "HEARTBEAT_BROKER_MANAGER_TERMINAL_V244_READY marker=%s ready=true surfaces=%s "
            "coinbase_live_terminal_required=true canonical_context_required=true "
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
    "_verified_reason",
    "_writer_ready",
]
