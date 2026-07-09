from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.execution_minimum_position_boundary_tolerance")
_MARKER = "20260709ag"
_PATCHED_ATTR = "_nija_execution_minimum_position_boundary_tolerance_20260709ag"


def _tol() -> float:
    try:
        return max(0.01, float(os.environ.get("NIJA_MIN_POSITION_BOUNDARY_TOLERANCE_USD", "0.01") or "0.01"))
    except Exception:
        return 0.01


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionMinimumPositionGate", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "validate_position_size", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    @wraps(original)
    def validate_position_size_with_boundary_tolerance(self: Any, position_size_usd: float, balance: float, symbol: str = "UNKNOWN", user_id: str | None = None):
        ok, reason, details = original(self, position_size_usd, balance, symbol=symbol, user_id=user_id)
        if ok:
            return ok, reason, details
        try:
            min_usd = float((details or {}).get("min_size_usd") or 0.0)
            size = float(position_size_usd or 0.0)
            tolerance = _tol()
        except Exception:
            return ok, reason, details
        reason_text = str(reason or "").lower()
        if min_usd > 0 and size > 0 and size + tolerance >= min_usd and "below minimum" in reason_text:
            logger.warning(
                "EXECUTION_MIN_POSITION_BOUNDARY_TOLERANCE_APPLIED marker=%s symbol=%s size=$%.8f min=$%.8f tolerance=$%.4f old_reason=%s",
                _MARKER,
                symbol,
                size,
                min_usd,
                tolerance,
                reason,
            )
            print(
                f"[NIJA-PRINT] EXECUTION_MIN_POSITION_BOUNDARY_TOLERANCE_APPLIED marker={_MARKER} symbol={symbol} size=${size:.2f} min=${min_usd:.2f}",
                flush=True,
            )
            fixed_details = dict(details or {})
            fixed_details["boundary_tolerance_applied"] = True
            return True, f"Position size OK after boundary tolerance: ${size:.2f} >= ${min_usd:.2f}", fixed_details
        return ok, reason, details

    setattr(validate_position_size_with_boundary_tolerance, _PATCHED_ATTR, True)
    setattr(cls, "validate_position_size", validate_position_size_with_boundary_tolerance)
    logger.warning("EXECUTION_MIN_POSITION_BOUNDARY_TOLERANCE_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    print(f"[NIJA-PRINT] EXECUTION_MIN_POSITION_BOUNDARY_TOLERANCE_PATCHED marker={_MARKER}", flush=True)
    return True


def _patch_loaded() -> None:
    for name in ("bot.execution_minimum_position_gate", "execution_minimum_position_gate"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("EXECUTION_MIN_POSITION_BOUNDARY_TOLERANCE_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, "_NIJA_EXECUTION_MIN_POSITION_BOUNDARY_TOLERANCE_HOOK_20260709AG", False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if str(name).endswith("execution_minimum_position_gate") or "execution_minimum_position_gate" in str(name):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, "_NIJA_EXECUTION_MIN_POSITION_BOUNDARY_TOLERANCE_HOOK_20260709AG", True)
    logger.warning("EXECUTION_MIN_POSITION_BOUNDARY_TOLERANCE_IMPORT_HOOK marker=%s installed=true", _MARKER)


def install() -> None:
    install_import_hook()
