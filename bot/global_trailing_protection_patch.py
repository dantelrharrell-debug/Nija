from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

logger = logging.getLogger("nija.global_trailing_protection")
_MARKER = "GLOBAL_TRAILING_PROTECTION_PATCHED marker=20260706a"
_TRAILING_ATTR = "_nija_global_trailing_system_20260706a"
_MIRROR_ATTR = "_nija_global_trailing_mirror_20260706a"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return default


def _side(position: Mapping[str, Any]) -> str:
    return str(position.get("side") or "long").strip().lower()


def _entry_price(position: Mapping[str, Any]) -> float:
    return _safe_float(
        position.get("entry_price")
        or position.get("entry")
        or position.get("avg_entry_price")
        or position.get("fill_price")
        or position.get("current_price")
        or position.get("price"),
        0.0,
    )


def attach_global_trailing_protection(position: Any, *, source: str = "unknown") -> Any:
    """Attach SL/TP/TSL/TTP fields to a position without forcing an immediate sell.

    This function is intentionally metadata-only. It gives every platform/user
    position the same protection contract while allowing the existing exit engine
    to fire only when price/profit conditions are met.
    """
    if not _truthy("NIJA_GLOBAL_TRAILING_PROTECTION_ENABLED", "true"):
        return position
    if not isinstance(position, dict):
        return position

    entry = _entry_price(position)
    if entry <= 0:
        return position

    side = _side(position)
    sl_pct = max(0.0005, _float_env("NIJA_GLOBAL_STOP_LOSS_PCT", _float_env("MAX_SL_PCT", 0.003)))
    tp1_pct = max(0.0005, _float_env("NIJA_GLOBAL_TP1_PCT", _float_env("MIN_TP_PCT", 0.010)))
    tp2_pct = max(tp1_pct, _float_env("NIJA_GLOBAL_TP2_PCT", _float_env("NIJA_FALLBACK_REPAIR_MIN_TP2_PCT", 0.018)))
    tp3_pct = max(tp2_pct, _float_env("NIJA_GLOBAL_TP3_PCT", _float_env("NIJA_FALLBACK_REPAIR_MIN_TP3_PCT", 0.026)))
    trail_pct = max(0.001, _float_env("NIJA_GLOBAL_TRAILING_STOP_PCT", 0.005))
    trail_activation_pct = max(0.0005, _float_env("NIJA_GLOBAL_TRAILING_ACTIVATION_PCT", 0.0025))
    ttp_activation_pct = max(tp1_pct, _float_env("NIJA_GLOBAL_TRAILING_TP_ACTIVATION_PCT", tp1_pct))

    if side in {"short", "sell"}:
        default_sl = entry * (1 + sl_pct)
        tp_levels = [entry * (1 - tp1_pct), entry * (1 - tp2_pct), entry * (1 - tp3_pct)]
    else:
        default_sl = entry * (1 - sl_pct)
        tp_levels = [entry * (1 + tp1_pct), entry * (1 + tp2_pct), entry * (1 + tp3_pct)]

    current_sl = _safe_float(position.get("stop_loss"), 0.0)
    if current_sl <= 0:
        position["stop_loss"] = default_sl
    else:
        if side in {"short", "sell"}:
            position["stop_loss"] = min(current_sl, default_sl)
        else:
            position["stop_loss"] = max(current_sl, default_sl)

    if not position.get("take_profit") and not position.get("take_profits"):
        position["take_profit"] = list(tp_levels)
        position["take_profits"] = list(tp_levels)
    elif position.get("take_profit") and not position.get("take_profits"):
        position["take_profits"] = position.get("take_profit")
    elif position.get("take_profits") and not position.get("take_profit"):
        position["take_profit"] = position.get("take_profits")

    position.setdefault("remaining_size", 1.0)
    position["stop_loss_enabled"] = True
    position["take_profit_enabled"] = True
    position["trailing_stop_enabled"] = True
    position["trailing_take_profit_enabled"] = True
    position["global_trailing_protection"] = True
    position["global_protection_source"] = source
    position["trailing_stop_pct"] = trail_pct
    position["trailing_activation_pct"] = trail_activation_pct
    position["trailing_take_profit_activation_pct"] = ttp_activation_pct
    position["profit_lock_enabled"] = True
    position.setdefault("profit_lock_active", False)
    # Mark TSL/TTP as attached globally. Existing price/profit gates still decide when to exit.
    position["tsl_attached"] = True
    position["ttp_attached"] = True
    position.setdefault("tsl_active", True)
    position.setdefault("ttp_active", True)
    return position


def _patch_trailing_system(module: ModuleType) -> bool:
    cls = getattr(module, "NIJATrailingSystem", None)
    if not isinstance(cls, type):
        return False
    patched = False

    original_open = getattr(cls, "open_position", None)
    if callable(original_open) and not getattr(original_open, _TRAILING_ATTR, False):
        @wraps(original_open)
        def open_position(self: Any, *args: Any, **kwargs: Any):
            position = original_open(self, *args, **kwargs)
            attached = attach_global_trailing_protection(position, source="nija_trailing_system.open_position")
            try:
                position_id = args[0] if args else kwargs.get("position_id")
                logger.critical(
                    "GLOBAL_TRAILING_PROTECTION_ATTACHED marker=20260706a surface=open_position position_id=%s stop_loss=%s tp=%s tsl=%s ttp=%s",
                    position_id,
                    attached.get("stop_loss") if isinstance(attached, dict) else None,
                    attached.get("take_profit") if isinstance(attached, dict) else None,
                    bool(isinstance(attached, dict) and attached.get("trailing_stop_enabled")),
                    bool(isinstance(attached, dict) and attached.get("trailing_take_profit_enabled")),
                )
            except Exception:
                pass
            return attached

        setattr(open_position, _TRAILING_ATTR, True)
        setattr(cls, "open_position", open_position)
        patched = True

    original_manage = getattr(cls, "manage_position", None)
    if callable(original_manage) and not getattr(original_manage, _TRAILING_ATTR, False):
        @wraps(original_manage)
        def manage_position(self: Any, position_id: Any, *args: Any, **kwargs: Any):
            try:
                positions = getattr(self, "positions", {})
                if isinstance(positions, dict) and position_id in positions:
                    attach_global_trailing_protection(positions[position_id], source="nija_trailing_system.manage_position")
            except Exception as exc:
                logger.debug("GLOBAL_TRAILING_PROTECTION manage attach skipped: %s", exc)
            return original_manage(self, position_id, *args, **kwargs)

        setattr(manage_position, _TRAILING_ATTR, True)
        setattr(cls, "manage_position", manage_position)
        patched = True

    if patched:
        logger.warning("%s class=NIJATrailingSystem", _MARKER)
        print("[NIJA-PRINT] GLOBAL_TRAILING_PROTECTION_PATCHED marker=20260706a surface=nija_trailing_system", flush=True)
    return patched


def _patch_held_position_mirror(module: ModuleType) -> bool:
    builder = getattr(module, "_build_execution_position", None)
    if not callable(builder) or getattr(builder, _MIRROR_ATTR, False):
        return bool(getattr(builder, _MIRROR_ATTR, False))

    @wraps(builder)
    def _build_execution_position(*args: Any, **kwargs: Any):
        built = builder(*args, **kwargs)
        attached = attach_global_trailing_protection(built, source="held_position_execution_mirror")
        if isinstance(attached, dict):
            logger.critical(
                "GLOBAL_TRAILING_PROTECTION_ATTACHED marker=20260706a surface=held_position_mirror broker=%s symbol=%s stop_loss=%s tp=%s tsl=true ttp=true",
                attached.get("broker_name") or attached.get("broker"),
                attached.get("symbol"),
                attached.get("stop_loss"),
                attached.get("take_profit"),
            )
        return attached

    setattr(_build_execution_position, _MIRROR_ATTR, True)
    setattr(module, "_build_execution_position", _build_execution_position)
    logger.warning("%s module=%s surface=held_position_mirror", _MARKER, getattr(module, "__name__", "unknown"))
    print("[NIJA-PRINT] GLOBAL_TRAILING_PROTECTION_PATCHED marker=20260706a surface=held_position_mirror", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.nija_trailing_system", "nija_trailing_system"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_trailing_system(module) or patched
    for name in ("bot.held_position_execution_mirror_patch", "held_position_execution_mirror_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_held_position_mirror(module) or patched
    return patched


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_GLOBAL_TRAILING_PROTECTION_ENABLED", "true")
    os.environ.setdefault("NIJA_GLOBAL_STOP_LOSS_ENABLED", "true")
    os.environ.setdefault("NIJA_GLOBAL_TAKE_PROFIT_ENABLED", "true")
    os.environ.setdefault("NIJA_GLOBAL_TRAILING_STOP_ENABLED", "true")
    os.environ.setdefault("NIJA_GLOBAL_TRAILING_TAKE_PROFIT_ENABLED", "true")
    os.environ.setdefault("NIJA_GLOBAL_STOP_LOSS_PCT", os.environ.get("MAX_SL_PCT", "0.003"))
    os.environ.setdefault("NIJA_GLOBAL_TP1_PCT", os.environ.get("MIN_TP_PCT", "0.010"))
    os.environ.setdefault("NIJA_GLOBAL_TP2_PCT", os.environ.get("NIJA_FALLBACK_REPAIR_MIN_TP2_PCT", "0.018"))
    os.environ.setdefault("NIJA_GLOBAL_TP3_PCT", os.environ.get("NIJA_FALLBACK_REPAIR_MIN_TP3_PCT", "0.026"))
    os.environ.setdefault("NIJA_GLOBAL_TRAILING_STOP_PCT", "0.005")
    os.environ.setdefault("NIJA_GLOBAL_TRAILING_ACTIVATION_PCT", "0.0025")
    os.environ.setdefault("NIJA_GLOBAL_TRAILING_TP_ACTIVATION_PCT", os.environ.get("NIJA_GLOBAL_TP1_PCT", "0.010"))
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_GLOBAL_TRAILING_PROTECTION_HOOK", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("nija_trailing_system") or name.endswith("held_position_execution_mirror_patch"):
                _try_patch_loaded()
            else:
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("GLOBAL_TRAILING_PROTECTION hook failed name=%s error=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_GLOBAL_TRAILING_PROTECTION_HOOK", True)
    logger.warning(
        "GLOBAL_TRAILING_PROTECTION_IMPORT_HOOK marker=20260706a sl=%s tp1=%s tp2=%s tp3=%s trail=%s",
        os.environ.get("NIJA_GLOBAL_STOP_LOSS_PCT"),
        os.environ.get("NIJA_GLOBAL_TP1_PCT"),
        os.environ.get("NIJA_GLOBAL_TP2_PCT"),
        os.environ.get("NIJA_GLOBAL_TP3_PCT"),
        os.environ.get("NIJA_GLOBAL_TRAILING_STOP_PCT"),
    )


def install() -> None:
    install_import_hook()
