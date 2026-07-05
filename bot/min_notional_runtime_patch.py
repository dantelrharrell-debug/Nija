"""Adaptive minimum-notional runtime patch for NIJA micro-cap live accounts.

Keeps micro-cap sizing available for venues that support small orders while never
letting Kraken/global shared notional keys fall below Kraken's live safety floor.

Venue policy:
- Coinbase: configurable floor, default $1
- OKX: configurable floor, default $10
- Kraken: hard protected floor, default/minimum $23
- Shared MIN_TRADE_USD/MIN_NOTIONAL_OVERRIDE: protected to Kraken floor when
  Kraken is configured/enabled so a later Kraken route cannot inherit a $10 floor.
"""

from __future__ import annotations

import builtins
import logging
import os
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.min_notional_runtime_patch")
_PATCHED_ATTR = "__nija_adaptive_min_notional_patch__"
_KRAKEN_PROTECTED_KEYS = (
    "KRAKEN_MIN_NOTIONAL_USD",
    "NIJA_KRAKEN_MIN_NOTIONAL_USD",
    "NIJA_KRAKEN_MICRO_MIN_NOTIONAL_USD",
    "NIJA_KRAKEN_EFFECTIVE_MIN_NOTIONAL_USD",
    "NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD",
)
_SHARED_PROTECTED_KEYS = ("MIN_NOTIONAL_OVERRIDE", "MIN_TRADE_USD")


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


def _kraken_configured() -> bool:
    return bool(
        os.environ.get("KRAKEN_API_KEY")
        or os.environ.get("KRAKEN_API_SECRET")
        or os.environ.get("KRAKEN_USER_DAIVON_API_KEY")
        or os.environ.get("KRAKEN_USER_TANIA_API_KEY")
        or _truthy("NIJA_KRAKEN_ENABLED", True)
    )


def _kraken_live_floor() -> float:
    values = [23.0]
    for key in _KRAKEN_PROTECTED_KEYS:
        values.append(_float_env(key, 0.0))
    return max(values)


def _set_if_too_high(name: str, target: float) -> None:
    current = _float_env(name, target)
    if current > target:
        os.environ[name] = str(target)
        logger.warning("ADAPTIVE_MIN_NOTIONAL_ENV_DOWNSHIFT %s %.2f -> %.2f", name, current, target)
    elif name not in os.environ:
        os.environ[name] = str(target)


def _set_if_below(name: str, floor: float) -> None:
    current = _float_env(name, floor)
    if current < floor:
        os.environ[name] = str(floor)
        logger.warning("ADAPTIVE_MIN_NOTIONAL_ENV_PROTECTED %s %.2f -> %.2f", name, current, floor)
    elif name not in os.environ:
        os.environ[name] = str(floor)


def _protect_kraken_floor() -> None:
    if not _kraken_configured():
        return
    floor = _kraken_live_floor()
    for key in _KRAKEN_PROTECTED_KEYS:
        _set_if_below(key, floor)
    # These shared keys are read by legacy/global execution paths before broker
    # context is available.  Keep them at Kraken floor when Kraken is configured
    # so no later Kraken route inherits a $10 micro-cap floor.
    for key in _SHARED_PROTECTED_KEYS:
        _set_if_below(key, floor)


def normalize_min_notional_env() -> None:
    if not _truthy("NIJA_ADAPTIVE_MIN_NOTIONAL_ENABLED", True):
        return

    _protect_kraken_floor()

    # Do not permit the previous $50 startup guard to dominate micro-cap live
    # execution for non-Kraken venues.  Shared/Kraken keys are re-protected after
    # these downshifts so Kraken can never be lowered below its live floor.
    if not _kraken_configured():
        _set_if_too_high("MIN_NOTIONAL_OVERRIDE", _float_env("NIJA_MICRO_CAP_MIN_NOTIONAL_USD", 10.0))
        _set_if_too_high("MIN_TRADE_USD", _float_env("NIJA_MICRO_CAP_MIN_TRADE_USD", 10.0))
    _set_if_too_high("MIN_CASH_TO_BUY", _float_env("NIJA_MICRO_CAP_MIN_CASH_TO_BUY_USD", 5.0))
    _set_if_too_high("COINBASE_MIN_ORDER_USD", _float_env("NIJA_COINBASE_MICRO_MIN_ORDER_USD", 1.0))
    _set_if_too_high("OKX_MIN_ORDER_USD", _float_env("NIJA_OKX_MICRO_MIN_ORDER_USD", 10.0))
    _protect_kraken_floor()
    os.environ.setdefault("NIJA_MIN_NOTIONAL_SPENDABLE_CAP", "true")


def _broker_floor(broker_name: str, legacy: float) -> float:
    broker = str(broker_name or "").lower()
    if "coinbase" in broker:
        return _float_env("COINBASE_MIN_ORDER_USD", 1.0)
    if "okx" in broker:
        return _float_env("OKX_MIN_ORDER_USD", 10.0)
    if "kraken" in broker:
        return _kraken_live_floor()
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
            "kraken": _kraken_live_floor(),
            "binance": min(10.0, env_floor),
            "okx": _float_env("OKX_MIN_ORDER_USD", 10.0),
            "alpaca": min(1.0, env_floor),
        }

    def get_min_notional_for_broker(self: Any, broker_name: str, balance: float = 0.0) -> float:
        normalize_min_notional_env()
        legacy = float(getattr(self, "min_entry_notional_usd", _float_env("MIN_TRADE_USD", 10.0)) or 10.0)
        floor = _broker_floor(broker_name, legacy)
        broker = str(broker_name or "").lower()
        # Never cap Kraken below its exchange/live floor.  Failing before submit is
        # safer than submitting a known-underfloor Kraken order and receiving an
        # exchange-side reject.
        if "kraken" not in broker and _truthy("NIJA_MIN_NOTIONAL_SPENDABLE_CAP", True) and balance and balance > 0:
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
                if current != target:
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
