"""Adaptive minimum-notional runtime patch for NIJA micro-cap live accounts.

The execution path previously forced live minimums to $50 through startup env
normalization.  That is too high for small accounts where the exchange-spendable
balance can be ~$15, causing valid entries to die at:

    stage=minimum_notional_gate reason=below_min_notional_spendable

This module restores venue-aware micro-cap floors without disabling safety:
- Coinbase: configurable floor, default $1
- Kraken: configurable floor, default $10
- OKX: configurable floor, default $10
- Global MIN_TRADE_USD/MIN_NOTIONAL_OVERRIDE: default $10

The gate still rejects orders below the applicable venue floor, but it no longer
uses an artificial $50 platform policy floor for micro-cap accounts.
"""

from __future__ import annotations

import builtins
import logging
import os
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.min_notional_runtime_patch")
_PATCHED_ATTR = "__nija_adaptive_min_notional_patch__"


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y", "enabled"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _set_if_too_high(name: str, target: float) -> None:
    current = _float_env(name, target)
    if current > target:
        os.environ[name] = str(target)
        logger.warning("ADAPTIVE_MIN_NOTIONAL_ENV_DOWNSHIFT %s %.2f -> %.2f", name, current, target)
    elif name not in os.environ:
        os.environ[name] = str(target)


def normalize_min_notional_env() -> None:
    if not _truthy("NIJA_ADAPTIVE_MIN_NOTIONAL_ENABLED", True):
        return
    # Do not permit the previous $50 startup guard to dominate micro-cap live
    # execution. These are policy floors; exchange hard-min validation remains
    # in the compiler/adapter layer.
    _set_if_too_high("MIN_NOTIONAL_OVERRIDE", _float_env("NIJA_MICRO_CAP_MIN_NOTIONAL_USD", 10.0))
    _set_if_too_high("MIN_TRADE_USD", _float_env("NIJA_MICRO_CAP_MIN_TRADE_USD", 10.0))
    _set_if_too_high("MIN_CASH_TO_BUY", _float_env("NIJA_MICRO_CAP_MIN_CASH_TO_BUY_USD", 5.0))
    _set_if_too_high("KRAKEN_MIN_NOTIONAL_USD", _float_env("NIJA_KRAKEN_MICRO_MIN_NOTIONAL_USD", 10.0))
    _set_if_too_high("COINBASE_MIN_ORDER_USD", _float_env("NIJA_COINBASE_MICRO_MIN_ORDER_USD", 1.0))
    _set_if_too_high("OKX_MIN_ORDER_USD", _float_env("NIJA_OKX_MICRO_MIN_ORDER_USD", 10.0))
    os.environ.setdefault("NIJA_MIN_NOTIONAL_SPENDABLE_CAP", "true")


def _broker_floor(broker_name: str, legacy: float) -> float:
    broker = str(broker_name or "").lower()
    if "coinbase" in broker:
        return _float_env("COINBASE_MIN_ORDER_USD", 1.0)
    if "okx" in broker:
        return _float_env("OKX_MIN_ORDER_USD", 10.0)
    if "kraken" in broker:
        return _float_env("KRAKEN_MIN_NOTIONAL_USD", 10.0)
    return min(float(legacy or 10.0), _float_env("MIN_TRADE_USD", 10.0))


def _patch_minimum_notional_gate(module: Any) -> bool:
    config_cls = getattr(module, "NotionalGateConfig", None)
    gate_cls = getattr(module, "MinimumNotionalGate", None)
    if not isinstance(config_cls, type) or not isinstance(gate_cls, type):
        return False
    if getattr(module, _PATCHED_ATTR, False):
        return True

    original_post_init = getattr(config_cls, "__post_init__", None)

    def __post_init__(self: Any) -> None:
        normalize_min_notional_env()
        if callable(original_post_init):
            original_post_init(self)
        env_floor = _float_env("MIN_NOTIONAL_OVERRIDE", _float_env("MIN_TRADE_USD", 10.0))
        self.min_entry_notional_usd = min(float(getattr(self, "min_entry_notional_usd", env_floor) or env_floor), env_floor)
        self.broker_specific_limits = {
            "coinbase": _float_env("COINBASE_MIN_ORDER_USD", 1.0),
            "kraken": _float_env("KRAKEN_MIN_NOTIONAL_USD", 10.0),
            "binance": min(10.0, env_floor),
            "okx": _float_env("OKX_MIN_ORDER_USD", 10.0),
            "alpaca": min(1.0, env_floor),
        }

    def get_min_notional_for_broker(self: Any, broker_name: str, balance: float = 0.0) -> float:
        normalize_min_notional_env()
        legacy = float(getattr(self, "min_entry_notional_usd", _float_env("MIN_TRADE_USD", 10.0)) or 10.0)
        floor = _broker_floor(broker_name, legacy)
        # If the only available spendable capital is below an artificial policy
        # floor, cap to available capital so the execution engine can attempt the
        # largest safe order instead of returning below_min_notional_spendable.
        if _truthy("NIJA_MIN_NOTIONAL_SPENDABLE_CAP", True) and balance and balance > 0:
            floor = min(floor, float(balance))
        return max(1.0, float(floor))

    original_validate = getattr(gate_cls, "validate_entry_size", None)

    def validate_entry_size(self: Any, symbol: str, size_usd: float, is_stop_loss: bool = False, broker_name: str | None = None, balance: float = 0.0):
        normalize_min_notional_env()
        if broker_name:
            min_floor = self.config.get_min_notional_for_broker(broker_name, balance=balance)
            if float(size_usd or 0.0) < min_floor:
                return False, f"Entry size ${float(size_usd or 0.0):.2f} below adaptive minimum notional ${min_floor:.2f} USD ({broker_name} requirement)"
            return True, None
        if callable(original_validate):
            return original_validate(self, symbol, size_usd, is_stop_loss, broker_name, balance)
        return True, None

    setattr(config_cls, "__post_init__", __post_init__)
    setattr(config_cls, "get_min_notional_for_broker", get_min_notional_for_broker)
    setattr(gate_cls, "validate_entry_size", validate_entry_size)

    # Reset singleton so the patched config is used even if the module was
    # imported before this patch.
    try:
        setattr(module, "_default_gate", None)
    except Exception:
        pass
    setattr(module, _PATCHED_ATTR, True)
    logger.warning("ADAPTIVE_MIN_NOTIONAL_GATE_PATCHED")
    return True


def _patch_execution_engine(module: Any) -> bool:
    if module is None:
        return False
    normalize_min_notional_env()
    changed = False
    for attr, target in (
        ("MIN_NOTIONAL_USD", _float_env("MIN_NOTIONAL_OVERRIDE", 10.0)),
        ("MIN_TRADE_USD", _float_env("MIN_TRADE_USD", 10.0)),
        ("MIN_CASH_TO_BUY", _float_env("MIN_CASH_TO_BUY", 5.0)),
    ):
        if hasattr(module, attr):
            try:
                current = float(getattr(module, attr) or 0.0)
                if current > target:
                    setattr(module, attr, target)
                    changed = True
            except Exception:
                pass
    if changed:
        logger.warning("ADAPTIVE_MIN_NOTIONAL_EXECUTION_ENGINE_CONSTANTS_PATCHED")
    return changed


def install_import_hook() -> None:
    normalize_min_notional_env()
    import sys

    for name, module in list(sys.modules.items()):
        if name.endswith("minimum_notional_gate"):
            _patch_minimum_notional_gate(module)
        if name.endswith("execution_engine"):
            _patch_execution_engine(module)

    if getattr(builtins, "_NIJA_MIN_NOTIONAL_PATCH_HOOK_INSTALLED", False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("minimum_notional_gate"):
                _patch_minimum_notional_gate(module)
            if name.endswith("execution_engine"):
                _patch_execution_engine(module)
        except Exception as exc:
            logger.warning("Adaptive min-notional runtime patch failed for %s: %s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_MIN_NOTIONAL_PATCH_HOOK_INSTALLED", True)
