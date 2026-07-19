"""Final broker-local minimum, Coinbase balance, and quarantined-OKX convergence.

This patch does not bypass broker minimums or risk controls. It removes the Kraken
minimum from global pre-routing state, preserves verified Coinbase balances across
transient zero reads on both import identities, and treats an intentionally
quarantined OKX venue as deferred rather than a global convergence failure.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.broker_local_minimum_coinbase_okx")
_MARKER = "20260719-broker-local-minimum-coinbase-okx-v1"
_LOCK = threading.RLock()
_INSTALLED = False


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)) or default)
    except Exception:
        return default


def _apply_broker_local_minimums() -> None:
    kraken = max(23.0, _f("KRAKEN_MIN_NOTIONAL_USD", 23.0))
    coinbase = max(1.0, _f("COINBASE_MIN_ORDER_USD", 1.0))
    okx = max(10.0, _f("OKX_MIN_ORDER_USD", 10.0))
    for name in (
        "KRAKEN_MIN_NOTIONAL_USD", "NIJA_KRAKEN_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_MICRO_MIN_NOTIONAL_USD", "NIJA_KRAKEN_EFFECTIVE_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD",
    ):
        os.environ[name] = f"{kraken:.2f}"
    os.environ["COINBASE_MIN_ORDER_USD"] = f"{coinbase:.2f}"
    os.environ["OKX_MIN_ORDER_USD"] = f"{okx:.2f}"
    # Pre-routing must use the lowest enabled venue floor. The selected broker's
    # own gate still enforces its stricter exchange-specific minimum.
    global_floor = min(coinbase, okx, kraken)
    os.environ["MIN_TRADE_USD"] = f"{global_floor:.2f}"
    os.environ["MIN_POSITION_USD"] = f"{global_floor:.2f}"
    os.environ["MIN_NOTIONAL_OVERRIDE"] = f"{global_floor:.2f}"
    os.environ["NIJA_APPLY_GLOBAL_EXECUTABLE_MIN_TRADE"] = "false"
    os.environ["NIJA_BROKER_LOCAL_MINIMUMS_ACTIVE"] = "1"
    logger.critical(
        "BROKER_LOCAL_MINIMUMS_CONVERGED marker=%s global=%.2f coinbase=%.2f kraken=%.2f okx=%.2f",
        _MARKER, global_floor, coinbase, kraken, okx,
    )


def _patch_notional_floor() -> bool:
    module = importlib.import_module("bot.notional_floor_repair_patch")
    current = getattr(module, "stabilize", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_broker_local_v1", False):
        _apply_broker_local_minimums()
        return True

    @wraps(current)
    def stabilize(source: str) -> None:
        current(source)
        _apply_broker_local_minimums()

    stabilize._nija_broker_local_v1 = True  # type: ignore[attr-defined]
    stabilize.__wrapped__ = current  # type: ignore[attr-defined]
    module.stabilize = stabilize
    _apply_broker_local_minimums()
    return True


def _patch_coinbase_class(module: ModuleType) -> bool:
    cls = getattr(module, "CoinbaseBroker", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "get_account_balance", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_coinbase_zero_guard_v2", False):
        return True

    @wraps(current)
    def balance(self: Any, *args: Any, **kwargs: Any):
        candidates = []
        for attr in (
            "_nija_last_verified_coinbase_balance", "_nija_last_account_balance_usd",
            "_last_known_balance", "last_known_balance", "account_balance",
        ):
            try:
                value = float(getattr(self, attr, 0.0) or 0.0)
                if value > 0:
                    candidates.append(value)
            except Exception:
                pass
        previous = max(candidates) if candidates else None
        try:
            result = current(self, *args, **kwargs)
            value = float(result or 0.0)
        except Exception as exc:
            if previous is not None:
                logger.warning("COINBASE_BALANCE_EXCEPTION_CACHE_USED marker=%s cached=%.8f error=%s", _MARKER, previous, exc)
                return previous
            raise
        if value > 0:
            self._nija_last_verified_coinbase_balance = value
            self._nija_last_verified_coinbase_balance_at = time.time()
            return result
        age = time.time() - float(getattr(self, "_nija_last_verified_coinbase_balance_at", 0.0) or 0.0)
        if previous is not None and age <= 1800.0:
            logger.warning("COINBASE_BALANCE_ZERO_CACHE_USED marker=%s reported=0 cached=%.8f age_s=%.1f", _MARKER, previous, age)
            return previous
        return result

    balance._nija_coinbase_zero_guard_v2 = True  # type: ignore[attr-defined]
    balance.__wrapped__ = current  # type: ignore[attr-defined]
    cls.get_account_balance = balance
    return True


def _patch_coinbase_aliases() -> bool:
    ready = False
    for name in ("bot.broker_manager", "broker_manager"):
        try:
            ready = _patch_coinbase_class(importlib.import_module(name)) or ready
        except Exception:
            continue
    return ready


def _okx_quarantined() -> bool:
    text = " ".join(
        str(os.getenv(name, "")) for name in (
            "NIJA_OKX_CREDENTIAL_STATUS", "OKX_CREDENTIAL_STATUS",
            "NIJA_OKX_ACTIVATION_STATE", "OKX_ACTIVATION_STATE",
        )
    ).lower()
    return "quarant" in text or os.getenv("NIJA_OKX_TRADING_READY", "").lower() in {"0", "false", "no"}


def _patch_okx_pending_contract() -> bool:
    module = importlib.import_module("bot.final_account_router_exit_convergence_patch")
    current = getattr(module, "_patch_okx_router", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_quarantined_okx_deferred_v1", False):
        return True

    @wraps(current)
    def patch_okx_router() -> bool:
        ready = bool(current())
        if ready:
            return True
        if _okx_quarantined():
            os.environ["NIJA_OKX_ROUTER_DEFERRED"] = "1"
            logger.warning(
                "OKX_ROUTER_DEFERRED_QUARANTINED marker=%s broker_independent=true global_block=false",
                _MARKER,
            )
            return True
        return False

    patch_okx_router._nija_quarantined_okx_deferred_v1 = True  # type: ignore[attr-defined]
    patch_okx_router.__wrapped__ = current  # type: ignore[attr-defined]
    module._patch_okx_router = patch_okx_router
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        results = {
            "broker_local_minimums": _patch_notional_floor(),
            "coinbase_aliases": _patch_coinbase_aliases(),
            "okx_quarantine_contract": _patch_okx_pending_contract(),
        }
        if not all(results.values()):
            raise RuntimeError(f"broker_local_minimum_coinbase_okx_incomplete:{results}")
        _INSTALLED = True
        os.environ["NIJA_BROKER_LOCAL_MINIMUM_COINBASE_OKX_READY"] = "1"
        logger.critical("BROKER_LOCAL_MINIMUM_COINBASE_OKX_READY marker=%s results=%s", _MARKER, results)
        return True


__all__ = ["install"]
