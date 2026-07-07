from __future__ import annotations

import builtins
import importlib
import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.global_runtime_startup_guards")
_ORIGINAL_LOG_METHOD: Optional[Callable[..., Any]] = None
_KRAKEN_PATCH_LOG_SEEN: set[str] = set()
_KRAKEN_PATCH_LOG_PATTERNS = (
    "ECEL_KRAKEN_LIVE_FLOOR_PATCHED",
    "ECEL_KRAKEN_ENTRY_TARGET_PATCHED",
    "KRAKEN_ORDER_VALIDATOR_ENTRY_TARGET_PATCHED",
    "TIER_CONFIG_LOW_BALANCE_KRAKEN_GUARD_PATCHED",
    "BROKER_INTEGRATION_KRAKEN_ENTRY_TARGET_REBOUND",
)


def _set_defaults() -> None:
    os.environ.setdefault("NIJA_HELD_TRADE_CAP_GUARD_ENABLED", "true")
    os.environ.setdefault("NIJA_MAX_HELD_TRADES_PER_ACCOUNT", "8")
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
    os.environ.setdefault("NIJA_PRE_TRADE_STALE_EXPOSURE_RECONCILE_ENABLED", "true")
    os.environ.setdefault("NIJA_PRE_TRADE_STALE_EXPOSURE_MIN_USD", "25")
    os.environ.setdefault("NIJA_PRE_TRADE_STALE_EXPOSURE_TOLERANCE_USD", "5")


def _install_kraken_patch_log_dedupe() -> None:
    global _ORIGINAL_LOG_METHOD
    if getattr(builtins, "_NIJA_KRAKEN_PATCH_LOG_DEDUPE_20260706B", False):
        return
    _ORIGINAL_LOG_METHOD = logging.Logger._log

    def _deduped_log(self, level: int, msg: Any, args: Any, exc_info=None, extra=None, stack_info=False, stacklevel: int = 1):
        try:
            text = str(msg)
            pattern = next((p for p in _KRAKEN_PATCH_LOG_PATTERNS if p in text), None)
            if pattern:
                key = f"{getattr(self, 'name', '')}:{pattern}:{text}"
                if key in _KRAKEN_PATCH_LOG_SEEN:
                    return None
                _KRAKEN_PATCH_LOG_SEEN.add(key)
        except Exception:
            pass
        return _ORIGINAL_LOG_METHOD(self, level, msg, args, exc_info=exc_info, extra=extra, stack_info=stack_info, stacklevel=stacklevel)  # type: ignore[misc]

    logging.Logger._log = _deduped_log  # type: ignore[assignment]
    setattr(builtins, "_NIJA_KRAKEN_PATCH_LOG_DEDUPE_20260706B", True)
    logger.warning("KRAKEN_PATCH_LOG_DEDUPE_PATCHED marker=20260706b patterns=%s", ",".join(_KRAKEN_PATCH_LOG_PATTERNS))


def _install_module(module_name: str, marker: str) -> bool:
    try:
        try:
            module = importlib.import_module(f"bot.{module_name}")
        except Exception:
            module = importlib.import_module(module_name)
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        if callable(installer):
            installer()
            logger.warning("%s marker=20260706b", marker)
            return True
        logger.warning("%s_SKIPPED marker=20260706b reason=installer_missing", marker)
    except Exception as exc:
        logger.warning("%s_FAILED marker=20260706b error=%s", marker, exc)
    return False


def install() -> None:
    if getattr(builtins, "_NIJA_GLOBAL_RUNTIME_STARTUP_GUARDS_20260706B", False):
        return
    _set_defaults()
    _install_kraken_patch_log_dedupe()
    held_ok = _install_module("held_trade_cap_guard_patch", "HELD_TRADE_CAP_GUARD_GLOBAL_STARTUP_INSTALL_REQUESTED")
    trailing_ok = _install_module("global_trailing_protection_patch", "GLOBAL_TRAILING_PROTECTION_GLOBAL_STARTUP_INSTALL_REQUESTED")
    profit_position_ok = _install_module("profit_position_protection_patch", "PROFIT_POSITION_PROTECTION_GLOBAL_STARTUP_INSTALL_REQUESTED")
    stale_exposure_ok = _install_module("pre_trade_stale_exposure_reconcile_patch", "PRE_TRADE_STALE_EXPOSURE_RECONCILE_GLOBAL_STARTUP_INSTALL_REQUESTED")
    setattr(builtins, "_NIJA_GLOBAL_RUNTIME_STARTUP_GUARDS_20260706B", True)
    logger.warning(
        "GLOBAL_RUNTIME_STARTUP_GUARDS_INSTALLED marker=20260706b held_cap=%s global_trailing=%s profit_position=%s stale_exposure=%s cap=%s",
        held_ok,
        trailing_ok,
        profit_position_ok,
        stale_exposure_ok,
        os.environ.get("NIJA_MAX_HELD_TRADES_PER_ACCOUNT", "8"),
    )


def install_import_hook() -> None:
    install()
