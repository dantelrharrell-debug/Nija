"""Fail-closed installer for NIJA signal-to-order completion repairs."""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Callable

logger = logging.getLogger("nija.critical_runtime_repairs_v6")
_MARKER = "20260720-critical-runtime-repairs-v6"
_LOCK = threading.RLock()
_INSTALLED = False

# Order is intentional: normalize runtime identity and account state first, then
# repair scan data, candidate handoff, execution telemetry, and broker routing.
_REQUIRED = (
    "runtime_patch_idempotence_guard",
    "account_capital_isolation_v4_patch",
    "coinbase_connect_recursion_terminal_guard",
    "scan_symbol_sanitizer_patch",
    "kraken_equity_freshness_v3_patch",
    "bot.kraken_verified_cost_basis_recovery_patch",
    "bot.position_cost_basis_entry_lock_patch",
    "bot.phase3_execution_handoff_repair_patch",
    "bot.live_entry_completion_repair_patch",
    "bot.phase3_admission_trace_repair_patch",
    "bot.final_account_router_exit_convergence_patch",
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
            os.environ["NIJA_CRITICAL_RUNTIME_REPAIRS_V6_READY"] = "0"
            logger.critical(
                "CRITICAL_RUNTIME_REPAIRS_V6_FAILED marker=%s completed=%s next=%s error=%s",
                _MARKER,
                ",".join(completed),
                _REQUIRED[len(completed)] if len(completed) < len(_REQUIRED) else "unknown",
                exc,
                exc_info=True,
            )
            raise

        os.environ["NIJA_CRITICAL_RUNTIME_REPAIRS_V6_READY"] = "1"
        os.environ["NIJA_PHASE3_EXECUTION_HANDOFF_REQUIRED"] = "1"
        os.environ["NIJA_SIGNAL_TO_EXECUTION_TELEMETRY_REQUIRED"] = "1"
        os.environ["NIJA_OKX_ROUTER_CONVERGENCE_REQUIRED"] = "1"
        _INSTALLED = True
        logger.critical(
            "CRITICAL_RUNTIME_REPAIRS_V6_READY marker=%s modules=%s "
            "phase3_handoff=true execution_completion=true admission_trace=true "
            "okx_router_convergence=true fail_closed=true",
            _MARKER,
            ",".join(completed),
        )
        return True


__all__ = ["install"]
