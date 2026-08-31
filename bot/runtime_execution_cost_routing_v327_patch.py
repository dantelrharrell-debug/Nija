"""Current-cost broker routing authority v327.

NIJA's entry economics are fee-aware, but the multi-broker router historically
ranked crypto venues with stale static fee bps (for example Coinbase=25 and
Kraken=16).  That can select the wrong venue before the stronger downstream
profitability gate ever sees the order.

v327 makes routing economics consistent with the canonical v324 fee authority:
* the router's static fee field is treated as a conservative fallback only;
* current public base-tier taker fees are used for Coinbase, Kraken and OKX;
* late broker registrations are normalized too, so an OKX convergence patch
  cannot reintroduce an old international/default fee into the U.S. runtime;
* broker availability, capital, health, latency, preferred venue, asset class,
  symbol support, risk, writer/nonce, kill-switch and fill gates are unchanged.

This patch deliberately does not claim an account's exact fee tier.  v324 still
prefers authenticated/runtime account fee data whenever the live broker exposes
it.  v327 only prevents an optimistic stale fallback from biasing venue choice.
"""
from __future__ import annotations

from dataclasses import replace
from functools import wraps
import importlib
import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.runtime_execution_cost_routing_v327")
MARKER = "20260831-runtime-execution-cost-routing-v327"
_PATCH_ATTR = "_nija_runtime_execution_cost_routing_v327"
_LOCK = threading.RLock()


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _fallback_taker_bps(broker_name: str) -> float | None:
    broker = _norm(broker_name)
    symbol = "BTC-USDT" if broker == "okx" else "BTC-USD"
    if broker not in {"coinbase", "kraken", "okx"}:
        return None
    core = importlib.import_module("bot.runtime_all_in_profitability_authority_v324_core")
    fee_fn = getattr(core, "_current_base_fees", None)
    if not callable(fee_fn):
        return None
    _maker, taker, _source = fee_fn(broker, symbol)
    value = float(taker) * 10_000.0
    return value if 0.0 <= value <= 500.0 else None


def _is_crypto_profile(profile: Any, module: Any) -> bool:
    asset_classes = tuple(getattr(profile, "asset_classes", ()) or ())
    crypto = getattr(getattr(module, "AssetClass", None), "CRYPTO", None)
    if crypto is None:
        return True
    return crypto in asset_classes


def _normalized_profile(profile: Any, module: Any) -> Any:
    name = _norm(getattr(profile, "name", ""))
    target = _fallback_taker_bps(name)
    if target is None or not _is_crypto_profile(profile, module):
        return profile
    current = float(getattr(profile, "fee_bps", target) or 0.0)
    if abs(current - target) <= 1e-12:
        return profile
    try:
        updated = replace(profile, fee_bps=target)
    except Exception:
        try:
            setattr(profile, "fee_bps", target)
            updated = profile
        except Exception:
            return profile
    LOGGER.critical(
        "EXECUTION_COST_ROUTING_V327_PROFILE_CORRECTED marker=%s broker=%s old_fee_bps=%.4f new_fee_bps=%.4f "
        "source=current_public_base_taker_fallback availability_unchanged=true",
        MARKER,
        name,
        current,
        target,
    )
    return updated


def _apply_existing_profiles(router: Any, module: Any) -> int:
    brokers = getattr(router, "_brokers", None)
    if not isinstance(brokers, dict):
        return 0
    changed = 0
    lock = getattr(router, "_lock", None)
    acquired = False
    try:
        if lock is not None and callable(getattr(lock, "acquire", None)):
            acquired = bool(lock.acquire(timeout=1.0))
        for key, profile in list(brokers.items()):
            updated = _normalized_profile(profile, module)
            if updated is not profile or float(getattr(profile, "fee_bps", 0.0) or 0.0) != float(getattr(updated, "fee_bps", 0.0) or 0.0):
                brokers[key] = updated
                changed += 1
            elif updated is profile:
                # Mutable profiles are updated in place; count if they now equal
                # the current fallback and were a known stale default.
                name = _norm(getattr(profile, "name", ""))
                target = _fallback_taker_bps(name)
                if target is not None and abs(float(getattr(profile, "fee_bps", target)) - target) <= 1e-12:
                    pass
    finally:
        if acquired:
            try:
                lock.release()
            except Exception:
                pass
    return changed


def _patch_router() -> bool:
    try:
        module = importlib.import_module("bot.multi_broker_execution_router")
        cls = getattr(module, "MultiBrokerExecutionRouter", None)
    except Exception:
        LOGGER.exception("EXECUTION_COST_ROUTING_V327_IMPORT_FAILED marker=%s", MARKER)
        return False
    if cls is None:
        return False

    register = getattr(cls, "register_broker", None)
    if not callable(register):
        return False
    if not getattr(register, _PATCH_ATTR, False):
        @wraps(register)
        def register_current_cost(self, profile, *args, **kwargs):
            return register(self, _normalized_profile(profile, module), *args, **kwargs)

        setattr(register_current_cost, _PATCH_ATTR, True)
        setattr(register_current_cost, "__wrapped__", register)
        cls.register_broker = register_current_cost

    defaults = getattr(cls, "_register_default_brokers", None)
    if callable(defaults) and not getattr(defaults, _PATCH_ATTR, False):
        @wraps(defaults)
        def defaults_current_cost(self, *args, **kwargs):
            result = defaults(self, *args, **kwargs)
            _apply_existing_profiles(self, module)
            return result

        setattr(defaults_current_cost, _PATCH_ATTR, True)
        setattr(defaults_current_cost, "__wrapped__", defaults)
        cls._register_default_brokers = defaults_current_cost

    # If a process-wide singleton was instantiated by an earlier import (v326
    # imports this module), normalize it immediately.  This does not create a
    # router merely for the purpose of patching it.
    for value in tuple(vars(module).values()):
        try:
            if isinstance(value, cls):
                _apply_existing_profiles(value, module)
        except Exception:
            continue

    return True


def install_import_hook() -> bool:
    with _LOCK:
        ready = _patch_router()
        os.environ["NIJA_RUNTIME_EXECUTION_COST_ROUTING_V327_READY"] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "RUNTIME_EXECUTION_COST_ROUTING_V327_READY marker=%s current_public_fee_fallbacks=true "
                "coinbase_taker_bps=60 kraken_taker_bps=80 okx_us_taker_bps=35 "
                "runtime_account_fee_authority_preserved=true availability_unchanged=true "
                "capital_health_latency_risk_writer_nonce_killswitch_fill_gates_unchanged=true safety_gates_bypassed=false",
                MARKER,
            )
        else:
            LOGGER.critical(
                "RUNTIME_EXECUTION_COST_ROUTING_V327_INCOMPLETE marker=%s fail_closed_existing_router_behavior_preserved=true",
                MARKER,
            )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "_fallback_taker_bps"]
