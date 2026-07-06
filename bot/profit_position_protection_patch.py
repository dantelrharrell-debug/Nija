from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.profit_position_protection")
_MARKER = "PROFIT_POSITION_PROTECTION_PATCHED marker=20260706a"
_PROFIT_LOCK_ATTR = "_nija_profit_lock_global_protection_20260706a"
_HARVEST_ATTR = "_nija_profit_harvest_global_protection_20260706a"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return default


def _normal_side(value: Any) -> str:
    text = str(value or "long").strip().lower()
    if text in {"buy", "long", "enter_long", "open_long"}:
        return "long"
    if text in {"sell", "short", "enter_short", "open_short"}:
        return "short"
    return text or "long"


def _attach(position: dict[str, Any], source: str) -> dict[str, Any]:
    if not _truthy("NIJA_GLOBAL_TRAILING_PROTECTION_ENABLED", "true"):
        return position
    try:
        try:
            module = importlib.import_module("bot.global_trailing_protection_patch")
        except Exception:
            module = importlib.import_module("global_trailing_protection_patch")
        fn = getattr(module, "attach_global_trailing_protection", None)
        if callable(fn):
            return fn(position, source=source)
    except Exception as exc:
        logger.debug("global protection attach helper unavailable: %s", exc)
    return position


def _build_position(symbol: Any, side: Any, entry_price: Any, position_size_usd: Any, source: str) -> dict[str, Any] | None:
    sym = str(symbol or "").strip()
    entry = _safe_float(entry_price, 0.0)
    size = _safe_float(position_size_usd, 0.0)
    if not sym or entry <= 0:
        return None
    qty = size / entry if size > 0 else 0.0
    return {
        "symbol": sym,
        "side": _normal_side(side),
        "entry_price": entry,
        "current_price": entry,
        "quantity": qty,
        "qty": qty,
        "size_usd": size,
        "position_size": size,
        "position_source": source,
        "adopted_for_exit_management": True,
        "broker_name": os.environ.get("NIJA_LAST_EXECUTION_BROKER", "profit_manager"),
        "broker": os.environ.get("NIJA_LAST_EXECUTION_BROKER", "profit_manager"),
        "account_id": os.environ.get("NIJA_LAST_EXECUTION_ACCOUNT_ID", "platform"),
    }


def _log_attached(position: dict[str, Any], surface: str) -> None:
    logger.critical(
        "GLOBAL_TRAILING_PROTECTION_ATTACHED marker=20260706a surface=%s broker=%s symbol=%s account_id=%s stop_loss=%s tp=%s tsl=%s ttp=%s",
        surface,
        position.get("broker_name") or position.get("broker"),
        position.get("symbol"),
        position.get("account_id"),
        position.get("stop_loss"),
        position.get("take_profit"),
        bool(position.get("trailing_stop_enabled") or position.get("tsl_attached")),
        bool(position.get("trailing_take_profit_enabled") or position.get("ttp_attached")),
    )
    print(
        f"[NIJA-PRINT] GLOBAL_TRAILING_PROTECTION_ATTACHED marker=20260706a surface={surface} symbol={position.get('symbol')} broker={position.get('broker_name') or position.get('broker')}",
        flush=True,
    )


def _patch_profit_lock(module: ModuleType) -> bool:
    cls = getattr(module, "ProfitLockSystem", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "register_position", None)
    if not callable(original) or getattr(original, _PROFIT_LOCK_ATTR, False):
        return bool(getattr(original, _PROFIT_LOCK_ATTR, False))

    @wraps(original)
    def register_position(self: Any, symbol: str, side: str, entry_price: float, position_size_usd: float = 0.0):
        result = original(self, symbol, side, entry_price, position_size_usd)
        try:
            pos = _build_position(symbol, side, entry_price, position_size_usd, "profit_lock_system.register_position")
            if pos is not None:
                _log_attached(_attach(pos, "profit_lock_system.register_position"), "profit_lock_system")
        except Exception as exc:
            logger.warning("PROFIT_POSITION_PROTECTION_ATTACH_FAILED marker=20260706a surface=profit_lock_system error=%s", exc)
        return result

    setattr(register_position, _PROFIT_LOCK_ATTR, True)
    setattr(cls, "register_position", register_position)
    logger.warning("%s surface=profit_lock_system", _MARKER)
    print("[NIJA-PRINT] PROFIT_POSITION_PROTECTION_PATCHED marker=20260706a surface=profit_lock_system", flush=True)
    return True


def _patch_harvest(module: ModuleType) -> bool:
    cls = getattr(module, "ProfitHarvestLayer", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "register_position", None)
    if not callable(original) or getattr(original, _HARVEST_ATTR, False):
        return bool(getattr(original, _HARVEST_ATTR, False))

    @wraps(original)
    def register_position(self: Any, symbol: str, side: str, entry_price: float, position_size_usd: float, *args: Any, **kwargs: Any):
        result = original(self, symbol, side, entry_price, position_size_usd, *args, **kwargs)
        try:
            pos = _build_position(symbol, side, entry_price, position_size_usd, "profit_harvest_layer.register_position")
            if pos is not None:
                _log_attached(_attach(pos, "profit_harvest_layer.register_position"), "profit_harvest_layer")
        except Exception as exc:
            logger.warning("PROFIT_POSITION_PROTECTION_ATTACH_FAILED marker=20260706a surface=profit_harvest_layer error=%s", exc)
        return result

    setattr(register_position, _HARVEST_ATTR, True)
    setattr(cls, "register_position", register_position)
    logger.warning("%s surface=profit_harvest_layer", _MARKER)
    print("[NIJA-PRINT] PROFIT_POSITION_PROTECTION_PATCHED marker=20260706a surface=profit_harvest_layer", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.profit_lock_system", "profit_lock_system"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_profit_lock(module) or patched
    for name in ("bot.profit_harvest_layer", "profit_harvest_layer"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_harvest(module) or patched
    return patched


def install_import_hook() -> None:
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_PROFIT_POSITION_PROTECTION_HOOK_20260706A", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("profit_lock_system") or name.endswith("profit_harvest_layer"):
                _try_patch_loaded()
            else:
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("PROFIT_POSITION_PROTECTION hook failed name=%s error=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_PROFIT_POSITION_PROTECTION_HOOK_20260706A", True)
    logger.warning("PROFIT_POSITION_PROTECTION_IMPORT_HOOK marker=20260706a")


def install() -> None:
    install_import_hook()
