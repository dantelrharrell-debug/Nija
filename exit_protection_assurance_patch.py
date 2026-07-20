"""Assure fixed and trailing exit protections remain active for every engine.

This module is deliberately lightweight at interpreter startup. It installs an
import hook and patches the canonical automatic exit module only after that
module loads. It does not bypass writer authority, broker readiness, position
ownership, order validation, or fill accounting.
"""
from __future__ import annotations

import builtins
import logging
import os
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.exit_protection_assurance")
_MARKER = "20260720-exit-protection-assurance-v1"
_PATCHED = "__nija_exit_protection_assurance_v1__"
_HOOK = "_NIJA_EXIT_PROTECTION_ASSURANCE_IMPORT_HOOK_V1"


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _configure() -> None:
    defaults = {
        "NIJA_AUTO_EXIT_SL_TP_ENABLED": "true",
        "NIJA_AUTO_EXIT_POLL_SECONDS": "3",
        "NIJA_HARD_STOP_LOSS_PCT": "0.015",
        "NIJA_MAX_POSITION_LOSS_USD": "2.00",
        "NIJA_PROFIT_TAKE_ENABLED": "true",
        "NIJA_PROFIT_LOCK_ACTIVATION_PCT": "0.008",
        "NIJA_PROFIT_LOCK_CALLBACK_PCT": "0.0035",
        "NIJA_TRAILING_STOP_ENABLED": "true",
        "NIJA_TRAILING_STOP_ACTIVATION_PCT": "0.008",
        "NIJA_TRAILING_STOP_PCT": "0.0035",
        "NIJA_TRAILING_TP_ENABLED": "true",
        "NIJA_TRAILING_TP_ACTIVATION_PCT": "0.008",
        "NIJA_TRAILING_TP_CALLBACK_PCT": "0.0035",
        "NIJA_COMBINED_TRAILING_TP_SL_ENABLED": "true",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def _patch(module: ModuleType) -> bool:
    if getattr(module, _PATCHED, False):
        return True
    trigger = getattr(module, "_trigger", None)
    position_key = getattr(module, "_position_key", None)
    entry_price = getattr(module, "_entry_price", None)
    side_fn = getattr(module, "_side", None)
    high_water = getattr(module, "_HIGH_WATER", None)
    if not all((callable(trigger), callable(position_key), callable(entry_price), callable(side_fn), isinstance(high_water, dict))):
        return False

    original_trigger: Callable[[dict[str, Any], float], tuple[bool, str, float]] = trigger

    def assured_trigger(pos: dict[str, Any], price: float) -> tuple[bool, str, float]:
        hit, reason, target = original_trigger(pos, price)
        if hit:
            return hit, reason, target

        # The canonical monitor already handles fixed TP, hard SL and long-side
        # profit-lock trailing exits. Add symmetric short-side trailing profit.
        side = str(side_fn(pos.get("side"), pos) or "").lower()
        entry = _f(entry_price(pos))
        if side not in {"short", "sell"} or entry <= 0 or price <= 0:
            return False, "", 0.0

        key = str(position_key(pos))
        previous_low = _f(high_water.get(key), entry)
        low = min(previous_low, price)
        high_water[key] = low
        activation = max(0.0, _f(os.environ.get("NIJA_PROFIT_LOCK_ACTIVATION_PCT"), 0.008))
        callback = max(0.0005, _f(os.environ.get("NIJA_PROFIT_LOCK_CALLBACK_PCT"), 0.0035))
        trigger_price = low * (1 + callback)
        if low <= entry * (1 - activation) and price >= trigger_price:
            return True, "profit_lock_trailing_exit", trigger_price
        return False, "", 0.0

    assured_trigger.__name__ = getattr(trigger, "__name__", "_trigger")
    assured_trigger.__doc__ = getattr(trigger, "__doc__", None)
    assured_trigger.__wrapped__ = trigger  # type: ignore[attr-defined]
    module._trigger = assured_trigger
    setattr(module, _PATCHED, True)
    os.environ["NIJA_EXIT_PROTECTION_ASSURANCE_READY"] = "1"
    logger.critical(
        "EXIT_PROTECTION_ASSURANCE_READY marker=%s fixed_take_profit=%s hard_stop_loss=%s trailing_take_profit=%s trailing_stop_loss=%s long_short_symmetric=true",
        _MARKER,
        _truthy("NIJA_PROFIT_TAKE_ENABLED"),
        _truthy("NIJA_AUTO_EXIT_SL_TP_ENABLED"),
        _truthy("NIJA_TRAILING_TP_ENABLED"),
        _truthy("NIJA_TRAILING_STOP_ENABLED"),
    )
    return True


def install_import_hook() -> None:
    import sys

    _configure()
    for name in ("bot.auto_exit_sl_tp_runtime_patch", "auto_exit_sl_tp_runtime_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch(module)

    if getattr(builtins, _HOOK, False):
        return
    original_import = builtins.__import__

    def hook(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("auto_exit_sl_tp_runtime_patch"):
                candidate = sys.modules.get(name)
                if isinstance(candidate, ModuleType):
                    _patch(candidate)
        except Exception:
            logger.exception("EXIT_PROTECTION_ASSURANCE_PATCH_FAILED marker=%s module=%s", _MARKER, name)
        return module

    builtins.__import__ = hook
    setattr(builtins, _HOOK, True)
    logger.warning("EXIT_PROTECTION_ASSURANCE_IMPORT_HOOK_INSTALLED marker=%s", _MARKER)


def install() -> None:
    install_import_hook()


__all__ = ["install", "install_import_hook", "_patch"]
