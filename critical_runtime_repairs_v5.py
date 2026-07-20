"""Canonical fail-closed installer for NIJA's July 20 critical runtime repairs."""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Callable

logger = logging.getLogger("nija.critical_runtime_repairs_v5")
_MARKER = "20260720-critical-runtime-repairs-v5"
_LOCK = threading.RLock()
_INSTALLED = False

_REQUIRED = (
    "runtime_patch_idempotence_guard",
    "account_capital_isolation_v4_patch",
    "coinbase_connect_recursion_terminal_guard",
    "scan_symbol_sanitizer_patch",
    "kraken_equity_freshness_v3_patch",
    "bot.kraken_verified_cost_basis_recovery_patch",
    "bot.position_cost_basis_entry_lock_patch",
)


def _installer(module_name: str) -> Callable[[], object]:
    module = importlib.import_module(module_name)
    installer = getattr(module, "install", None) or getattr(module, "install_import_hook", None)
    if not callable(installer):
        raise RuntimeError(f"required_installer_missing:{module_name}")
    return installer


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        completed: list[str] = []
        try:
            for module_name in _REQUIRED:
                _installer(module_name)()
                completed.append(module_name)
        except Exception as exc:
            os.environ["NIJA_CRITICAL_RUNTIME_REPAIRS_V5_READY"] = "0"
            logger.critical(
                "CRITICAL_RUNTIME_REPAIRS_V5_FAILED marker=%s completed=%s failed_after=%s error=%s",
                _MARKER, ",".join(completed), completed[-1] if completed else "none", exc,
                exc_info=True,
            )
            raise
        os.environ["NIJA_CRITICAL_RUNTIME_REPAIRS_V5_READY"] = "1"
        _INSTALLED = True
        logger.critical(
            "CRITICAL_RUNTIME_REPAIRS_V5_READY marker=%s modules=%s account_isolation=true user_mode_enforced=true "
            "coinbase_recursion_terminal=true symbol_sanitizer=true kraken_fresh_equity=true "
            "verified_cost_basis=true unverified_entry_lock=true",
            _MARKER, ",".join(completed),
        )
        return True


__all__ = ["install"]
