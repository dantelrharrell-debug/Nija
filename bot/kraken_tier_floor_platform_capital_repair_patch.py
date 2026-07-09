from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.kraken_tier_floor_platform_capital_repair")
_MARKER = "20260709ad"
_VALIDATE_ATTR = "_nija_kraken_tier_floor_platform_capital_repair_validate_20260709ad"
_RESIZE_ATTR = "_nija_kraken_tier_floor_platform_capital_repair_resize_20260709ad"
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


def _exchange_min(exchange: str) -> float:
    exchange_l = str(exchange or "").strip().lower()
    if exchange_l == "kraken":
        return max(10.0, _f(os.environ.get("KRAKEN_MIN_NOTIONAL_USD"), _f(os.environ.get("MIN_TRADE_USD"), 10.0)))
    if exchange_l == "coinbase":
        return max(1.0, _f(os.environ.get("COINBASE_MIN_ORDER_USD"), 1.0))
    if exchange_l == "okx":
        return max(5.0, _f(os.environ.get("OKX_MIN_ORDER_USD"), 10.0))
    return max(1.0, _f(os.environ.get("MIN_TRADE_USD"), 10.0))


def _platform_total_capital() -> float:
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except Exception:
            from capital_authority import get_capital_authority  # type: ignore
        ca = get_capital_authority()
        for attr in ("get_real_capital", "get_total_capital"):
            reader = getattr(ca, attr, None)
            if callable(reader):
                amount = _f(reader(), 0.0)
                if amount > 0:
                    return amount
        for attr in ("total_capital", "real_capital", "total"):
            amount = _f(getattr(ca, attr, 0.0), 0.0)
            if amount > 0:
                return amount
    except Exception:
        pass
    return _f(os.environ.get("NIJA_PLATFORM_TOTAL_CAPITAL_USD"), 0.0)


def _should_repair(exchange: str, trade_size: float, balance: float, is_platform: bool) -> bool:
    if not _truthy("NIJA_KRAKEN_TIER_FLOOR_PLATFORM_CAPITAL_REPAIR", "true"):
        return False
    if is_platform:
        return False
    if str(exchange or "").strip().lower() != "kraken":
        return False
    balance_f = _f(balance, 0.0)
    trade_f = _f(trade_size, 0.0)
    if balance_f < _f(os.environ.get("NIJA_KRAKEN_MIN_ACCOUNT_CASH_FOR_REPAIR"), 100.0):
        return False
    if trade_f + 1e-9 < _exchange_min("kraken"):
        return False
    platform_total = _platform_total_capital()
    required_platform = _f(os.environ.get("NIJA_KRAKEN_PLATFORM_CAPITAL_REPAIR_MIN_TOTAL"), 250.0)
    return platform_total >= required_platform


def _patch_tier_config(module: ModuleType) -> bool:
    patched = False
    original_validate = getattr(module, "validate_trade_size", None)
    if callable(original_validate) and not getattr(original_validate, _VALIDATE_ATTR, False):
        @wraps(original_validate)
        def validate_trade_size_repaired(trade_size: float, tier: Any, balance: float, is_platform: bool = False, exchange: str = "coinbase"):
            ok, reason = original_validate(trade_size, tier, balance, is_platform=is_platform, exchange=exchange)
            if ok:
                return ok, reason
            reason_text = str(reason or "").lower()
            if (
                _should_repair(exchange, trade_size, balance, is_platform)
                and ("tier minimum" in reason_text or "below minimum" in reason_text)
            ):
                logger.warning(
                    "KRAKEN_TIER_FLOOR_PLATFORM_CAPITAL_REPAIRED marker=%s surface=validate_trade_size trade=$%.2f broker_balance=$%.2f platform_total=$%.2f tier=%s old_reason=%s",
                    _MARKER,
                    _f(trade_size, 0.0),
                    _f(balance, 0.0),
                    _platform_total_capital(),
                    getattr(tier, "value", tier),
                    reason,
                )
                return True, "valid after kraken platform-capital tier-floor repair"
            return ok, reason

        setattr(validate_trade_size_repaired, _VALIDATE_ATTR, True)
        setattr(module, "validate_trade_size", validate_trade_size_repaired)
        patched = True

    original_resize = getattr(module, "auto_resize_trade", None)
    if callable(original_resize) and not getattr(original_resize, _RESIZE_ATTR, False):
        @wraps(original_resize)
        def auto_resize_trade_repaired(trade_size: float, tier: Any, balance: float, is_platform: bool = False, exchange: str = "coinbase"):
            resized, reason = original_resize(trade_size, tier, balance, is_platform=is_platform, exchange=exchange)
            if _f(resized, 0.0) > 0:
                return resized, reason
            reason_text = str(reason or "").lower()
            if (
                _should_repair(exchange, trade_size, balance, is_platform)
                and ("below minimum" in reason_text or "cannot resize up" in reason_text)
            ):
                repaired = max(_f(trade_size, 0.0), _exchange_min("kraken"))
                logger.warning(
                    "KRAKEN_TIER_FLOOR_PLATFORM_CAPITAL_RESIZE_REPAIRED marker=%s trade=$%.2f repaired=$%.2f broker_balance=$%.2f platform_total=$%.2f tier=%s old_reason=%s",
                    _MARKER,
                    _f(trade_size, 0.0),
                    repaired,
                    _f(balance, 0.0),
                    _platform_total_capital(),
                    getattr(tier, "value", tier),
                    reason,
                )
                return repaired, "valid after kraken platform-capital tier-floor repair"
            return resized, reason

        setattr(auto_resize_trade_repaired, _RESIZE_ATTR, True)
        setattr(module, "auto_resize_trade", auto_resize_trade_repaired)
        patched = True

    if patched:
        logger.warning("KRAKEN_TIER_FLOOR_PLATFORM_CAPITAL_REPAIR_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
        print(f"[NIJA-PRINT] KRAKEN_TIER_FLOOR_PLATFORM_CAPITAL_REPAIR_PATCHED marker={_MARKER}", flush=True)
    return patched


def _patch_loaded() -> None:
    for name in ("bot.tier_config", "tier_config"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_tier_config(module)
            except Exception as exc:
                logger.warning("KRAKEN_TIER_FLOOR_PLATFORM_CAPITAL_REPAIR_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, "_NIJA_KRAKEN_TIER_FLOOR_PLATFORM_CAPITAL_REPAIR_HOOK_20260709AD", False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if str(name).endswith("tier_config") or "tier_config" in str(name):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, "_NIJA_KRAKEN_TIER_FLOOR_PLATFORM_CAPITAL_REPAIR_HOOK_20260709AD", True)
    logger.warning("KRAKEN_TIER_FLOOR_PLATFORM_CAPITAL_REPAIR_IMPORT_HOOK marker=%s installed=true", _MARKER)


def install() -> None:
    install_import_hook()
