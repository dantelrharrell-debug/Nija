from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.platform_tier_live_capital")
_MARKER = "20260709s"
_HOOK_FLAG = "_NIJA_PLATFORM_TIER_LIVE_CAPITAL_HOOK_V20260709S"
_TIER_ATTR = "_nija_platform_tier_live_capital_tier_v20260709s"
_VALIDATE_ATTR = "_nija_platform_tier_live_capital_validate_v20260709s"
_RESIZE_ATTR = "_nija_platform_tier_live_capital_resize_v20260709s"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        amount = float(value)
        if amount != amount:
            return default
        return amount
    except Exception:
        return default


def _live_platform_capital() -> float:
    best = 0.0
    for mod_name in ("bot.capital_authority", "capital_authority"):
        try:
            mod = __import__(mod_name, fromlist=["get_capital_authority"])
            getter = getattr(mod, "get_capital_authority", None)
            if not callable(getter):
                continue
            ca = getter()
            for attr in ("get_real_capital", "get_usable_capital", "total_capital", "real_capital", "usable_capital"):
                value = getattr(ca, attr, None)
                value = value() if callable(value) else value
                best = max(best, _f(value, 0.0))
        except Exception:
            pass
    return best


def _effective_balance(balance: Any, *, is_platform: bool = False) -> tuple[float, bool, float]:
    raw = _f(balance, 0.0)
    live = _live_platform_capital()
    platform_mode = is_platform or _truthy("NIJA_PLATFORM_EXECUTION_CAPITAL_ONLY", "true") or _truthy("NIJA_MASTER_SIGNAL_ONLY", "true")
    if platform_mode and live > raw and live >= _f(os.environ.get("NIJA_PLATFORM_TIER_LIVE_CAPITAL_MIN_USD"), 250.0):
        return live, True, raw
    return raw, False, live


def _patch_tier_config(module: ModuleType) -> bool:
    patched = False

    original_tier = getattr(module, "get_tier_from_balance", None)
    if callable(original_tier) and not getattr(original_tier, _TIER_ATTR, False):
        @wraps(original_tier)
        def get_tier_from_balance(balance: float, override_tier: str = None, is_platform: bool = False):
            effective, changed, live = _effective_balance(balance, is_platform=is_platform)
            if changed:
                logger.warning(
                    "PLATFORM_TIER_LIVE_CAPITAL_APPLIED marker=%s surface=get_tier_from_balance requested_balance=%.2f live_capital=%.2f effective_balance=%.2f",
                    _MARKER,
                    _f(balance, 0.0),
                    live,
                    effective,
                )
            return original_tier(effective, override_tier=override_tier, is_platform=is_platform)
        setattr(get_tier_from_balance, _TIER_ATTR, True)
        setattr(get_tier_from_balance, "__wrapped__", original_tier)
        setattr(module, "get_tier_from_balance", get_tier_from_balance)
        patched = True

    original_validate = getattr(module, "validate_trade_size", None)
    if callable(original_validate) and not getattr(original_validate, _VALIDATE_ATTR, False):
        @wraps(original_validate)
        def validate_trade_size(trade_size: float, tier: Any, balance: float, is_platform: bool = False, exchange: str = "coinbase"):
            effective, changed, live = _effective_balance(balance, is_platform=is_platform)
            if changed:
                logger.warning(
                    "PLATFORM_TIER_LIVE_CAPITAL_APPLIED marker=%s surface=validate_trade_size exchange=%s trade_size=%.2f requested_balance=%.2f live_capital=%.2f effective_balance=%.2f",
                    _MARKER,
                    exchange,
                    _f(trade_size, 0.0),
                    _f(balance, 0.0),
                    live,
                    effective,
                )
            return original_validate(trade_size, tier, effective, is_platform=is_platform, exchange=exchange)
        setattr(validate_trade_size, _VALIDATE_ATTR, True)
        setattr(validate_trade_size, "__wrapped__", original_validate)
        setattr(module, "validate_trade_size", validate_trade_size)
        patched = True

    original_resize = getattr(module, "auto_resize_trade", None)
    if callable(original_resize) and not getattr(original_resize, _RESIZE_ATTR, False):
        @wraps(original_resize)
        def auto_resize_trade(trade_size: float, tier: Any, balance: float, is_platform: bool = False, exchange: str = "coinbase"):
            effective, changed, live = _effective_balance(balance, is_platform=is_platform)
            if changed:
                logger.warning(
                    "PLATFORM_TIER_LIVE_CAPITAL_APPLIED marker=%s surface=auto_resize_trade exchange=%s trade_size=%.2f requested_balance=%.2f live_capital=%.2f effective_balance=%.2f",
                    _MARKER,
                    exchange,
                    _f(trade_size, 0.0),
                    _f(balance, 0.0),
                    live,
                    effective,
                )
            return original_resize(trade_size, tier, effective, is_platform=is_platform, exchange=exchange)
        setattr(auto_resize_trade, _RESIZE_ATTR, True)
        setattr(auto_resize_trade, "__wrapped__", original_resize)
        setattr(module, "auto_resize_trade", auto_resize_trade)
        patched = True

    if patched:
        logger.warning("PLATFORM_TIER_LIVE_CAPITAL_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", ""))
        print(f"[NIJA-PRINT] PLATFORM_TIER_LIVE_CAPITAL_PATCHED marker={_MARKER}", flush=True)
    return patched


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if isinstance(module, ModuleType) and name.endswith("tier_config"):
            try:
                patched = _patch_tier_config(module) or patched
            except Exception as exc:
                logger.warning("PLATFORM_TIER_LIVE_CAPITAL_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    return patched


def install_import_hook() -> None:
    _try_patch_loaded()
    if getattr(builtins, _HOOK_FLAG, False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if "tier_config" in str(name):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("PLATFORM_TIER_LIVE_CAPITAL_IMPORT_HOOK_FAILED marker=%s name=%s err=%s", _MARKER, name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _HOOK_FLAG, True)
    logger.warning("PLATFORM_TIER_LIVE_CAPITAL_IMPORT_HOOK marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
