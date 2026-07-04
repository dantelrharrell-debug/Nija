"""Keep live minimum notional values internally consistent."""

from __future__ import annotations

import builtins
import logging
import os
import sys
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.notional_floor_repair")
_TRUE = {"1", "true", "yes", "on", "y", "enabled"}
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_LOGGED = False


def _float_env(name: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(name, default))
    except Exception:
        return default


def _set_floor(name: str, value: float) -> bool:
    try:
        current = float(os.environ.get(name, "0") or 0.0)
    except Exception:
        current = 0.0
    if current < value:
        os.environ[name] = f"{value:.2f}"
        return True
    return False


def _floor() -> float:
    value = 23.0
    for name in (
        "KRAKEN_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_MICRO_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_EFFECTIVE_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD",
    ):
        value = max(value, _float_env(name, 0.0))
    return value


def stabilize(source: str) -> None:
    global _LOGGED
    value = _floor()
    changed: list[str] = []
    for name in (
        "KRAKEN_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_MICRO_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_EFFECTIVE_MIN_NOTIONAL_USD",
        "NIJA_KRAKEN_FINAL_MIN_NOTIONAL_USD",
        "MIN_TRADE_USD",
        "MIN_POSITION_USD",
        "MIN_NOTIONAL_OVERRIDE",
    ):
        if _set_floor(name, value):
            changed.append(name)
    os.environ["NIJA_APPLY_GLOBAL_EXECUTABLE_MIN_TRADE"] = "false"
    os.environ.setdefault("COINBASE_MIN_ORDER_USD", "1")
    os.environ.setdefault("OKX_MIN_ORDER_USD", "10")
    if changed or not _LOGGED:
        logger.warning("NOTIONAL_FLOOR_REPAIR source=%s floor=$%.2f changed=%s", source, value, changed or [])
        _LOGGED = True


def _patch_hardening(module: ModuleType) -> None:
    original = getattr(module, "normalize_live_execution_env", None)
    if not callable(original) or getattr(original, "_notional_floor_repair", False):
        return

    def normalize_live_execution_env() -> None:
        if str(os.environ.get("NIJA_LIVE_EXECUTION_HARDENING_ENABLED", "true")).strip().lower() not in _TRUE:
            return
        os.environ["NIJA_KRAKEN_PAIR_AWARE_MINIMUMS"] = "true"
        os.environ["NIJA_PLATFORM_EXECUTION_CAPITAL_ONLY"] = "true"
        os.environ["NIJA_AGGREGATE_USER_CAPITAL_IN_AUTHORITY"] = "false"
        stabilize("live_execution_runtime_hardening")

    normalize_live_execution_env._notional_floor_repair = True  # type: ignore[attr-defined]
    module.normalize_live_execution_env = normalize_live_execution_env  # type: ignore[attr-defined]
    logger.warning("LIVE_EXECUTION_NOTIONAL_FLOOR_REPAIR_PATCHED module=%s", getattr(module, "__name__", "?"))


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    stabilize("install")
    if _ORIGINAL_IMPORT is not None:
        return
    _ORIGINAL_IMPORT = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
        if str(getattr(module, "__name__", "")) in {"bot.live_execution_runtime_hardening_patch", "live_execution_runtime_hardening_patch"}:
            _patch_hardening(module)
        loaded = sys.modules.get("bot.live_execution_runtime_hardening_patch") or sys.modules.get("live_execution_runtime_hardening_patch")
        if loaded is not None:
            _patch_hardening(loaded)
        return module

    builtins.__import__ = importing
    loaded = sys.modules.get("bot.live_execution_runtime_hardening_patch") or sys.modules.get("live_execution_runtime_hardening_patch")
    if loaded is not None:
        _patch_hardening(loaded)
    logger.warning("NOTIONAL_FLOOR_REPAIR_INSTALLED marker=20260704g")
