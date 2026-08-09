"""NIJA deep runtime hardening bundle v70.

Single idempotent installer for the cross-cutting production hardening introduced
while preparing NIJA for additional brokerages and user accounts.  Individual
modules retain their own markers/tests and remain independently installable.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import threading

LOGGER = logging.getLogger("nija.deep_runtime_hardening_bundle_v70")
MARKER = "20260809-deep-runtime-hardening-bundle-v70"
_LOCK = threading.RLock()
_MODULES = (
    "bot.broker_account_isolation_v64_patch",
    "bot.profit_harvest_realization_guard_v66_patch",
    "bot.universal_exit_fill_reconciliation_v67_patch",
    "bot.universal_net_profit_exit_floor_v68_patch",
    "bot.live_entry_expectancy_authority_v69_patch",
    "bot.account_scoped_profit_state_v71_patch",
    "bot.live_exchange_constraints_authority_v72_patch",
    "bot.live_exchange_base_minimum_v73_patch",
    "bot.adaptive_profit_exit_v74_patch",
    "bot.held_position_exit_bootstrap_v75_patch",
)


def install_import_hook() -> bool:
    with _LOCK:
        installed: list[str] = []
        failed: list[str] = []
        for module_name in _MODULES:
            try:
                module = importlib.import_module(module_name)
                installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
                if not callable(installer):
                    raise RuntimeError("installer_missing")
                installer()
                installed.append(module_name)
            except Exception as exc:
                failed.append(f"{module_name}:{type(exc).__name__}:{exc}")
                LOGGER.exception(
                    "DEEP_RUNTIME_HARDENING_V70_COMPONENT_FAILED marker=%s module=%s",
                    MARKER,
                    module_name,
                )
        if failed:
            os.environ["NIJA_DEEP_RUNTIME_HARDENING_V70_READY"] = "0"
            LOGGER.critical(
                "DEEP_RUNTIME_HARDENING_V70_INCOMPLETE marker=%s installed=%s failed=%s fail_closed=true",
                MARKER,
                installed,
                failed,
            )
            return False
        setattr(builtins, "_NIJA_DEEP_RUNTIME_HARDENING_BUNDLE_V70", True)
        os.environ["NIJA_DEEP_RUNTIME_HARDENING_V70_READY"] = "1"
        LOGGER.critical(
            "DEEP_RUNTIME_HARDENING_V70_READY marker=%s components=%d "
            "broker_account_isolation=true exit_fill_confirmation=true net_profit_floor=true "
            "live_entry_expectancy=true realized_profit_proof=true account_scoped_profit_state=true "
            "live_symbol_constraints=true post_rounding_base_minimum=true "
            "adaptive_profit_exit=true held_positions_connected=true",
            MARKER,
            len(installed),
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook"]
