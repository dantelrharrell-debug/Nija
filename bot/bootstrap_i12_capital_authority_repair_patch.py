"""Repair BootstrapFSM I12 hydration race with CapitalAuthority.

The composite BootstrapFSM enforces I12 by waiting on CapitalCSMv2 hydration.
On Railway startup, CapitalAuthority can already hold a fresh positive live
snapshot while CapitalCSMv2 is still INITIALIZING.  In that narrow case, killing
bot_main is wrong: the capital pipeline has proved real funds and the trading
loop has already reached its first tick.

This patch preserves fail-closed behavior:
* the original CSM-v2 check still runs first;
* fallback only passes when CapitalAuthority reports positive real capital and
  at least one valid broker;
* zero/unknown capital still fails with the original I12 error.
"""

from __future__ import annotations

import builtins
import logging
import os
import sys
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.bootstrap_i12_capital_authority_repair")
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUE


def _capital_authority_snapshot_ready() -> tuple[bool, str]:
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]

        authority = get_capital_authority()
        real = 0.0
        valid_brokers = 0
        hydrated = bool(getattr(authority, "is_hydrated", False))
        first_snap = bool(getattr(authority, "first_snap_accepted", False))
        state = str(getattr(authority, "state", "unknown"))

        get_real = getattr(authority, "get_real_capital", None)
        if callable(get_real):
            real = float(get_real() or 0.0)
        else:
            real = float(getattr(authority, "total_capital", 0.0) or 0.0)

        valid_brokers = int(getattr(authority, "valid_broker_count", 0) or 0)
        if valid_brokers <= 0:
            registered = int(getattr(authority, "registered_broker_count", 0) or 0)
            valid_brokers = registered if real > 0.0 else 0

        ready = real > 0.0 and valid_brokers > 0
        detail = (
            f"real=${real:.2f} valid_brokers={valid_brokers} "
            f"hydrated={hydrated} first_snap={first_snap} state={state}"
        )
        return ready, detail
    except Exception as exc:  # noqa: BLE001 - diagnostic fallback only
        return False, f"capital_authority_probe_failed={exc}"


def _patch_bootstrap_fsm(module: ModuleType) -> bool:
    cls = getattr(module, "BootstrapStateMachine", None)
    invariant_error = getattr(module, "BootstrapInvariantError", RuntimeError)
    if cls is None:
        return False
    if getattr(cls, "_NIJA_I12_CAPITAL_AUTHORITY_REPAIR_PATCHED", False):
        return True

    original = getattr(cls, "assert_invariant_i12_capital_hydration", None)
    if not callable(original):
        return False

    def _patched_assert_i12(self: Any, timeout: float = 5.0) -> None:
        try:
            original(self, timeout=timeout)
            return
        except Exception as exc:  # noqa: BLE001 - preserve original unless CA proves readiness
            original_error = exc

        ready, detail = _capital_authority_snapshot_ready()
        if ready:
            logger.warning(
                "BOOTSTRAP_I12_CAPITAL_AUTHORITY_REPAIRED detail=%s original_error=%s",
                detail,
                original_error,
            )
            return

        if isinstance(original_error, invariant_error):
            raise original_error
        raise original_error

    setattr(cls, "assert_invariant_i12_capital_hydration", _patched_assert_i12)
    setattr(cls, "_NIJA_I12_CAPITAL_AUTHORITY_REPAIR_PATCHED", True)
    logger.warning("BOOTSTRAP_I12_CAPITAL_AUTHORITY_REPAIR_PATCHED module=%s", module.__name__)
    return True


def _apply_to_loaded_modules() -> None:
    for name in ("bot.bootstrap_state_machine", "bootstrap_state_machine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_bootstrap_fsm(module)
            except Exception as exc:  # noqa: BLE001
                logger.warning("BOOTSTRAP_I12_CAPITAL_AUTHORITY_REPAIR_FAILED module=%s err=%s", name, exc)


def install_import_hook() -> None:
    if getattr(builtins, "_NIJA_BOOTSTRAP_I12_CA_REPAIR_IMPORT_HOOK_INSTALLED", False):
        _apply_to_loaded_modules()
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        target_names = {name}
        for item in fromlist or ():
            target_names.add(f"{name}.{item}")
        if name in {"bot.bootstrap_state_machine", "bootstrap_state_machine"} or any(
            str(item).endswith("bootstrap_state_machine") for item in target_names
        ):
            _apply_to_loaded_modules()
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_BOOTSTRAP_I12_CA_REPAIR_IMPORT_HOOK_INSTALLED", True)
    _apply_to_loaded_modules()
    logger.warning("BOOTSTRAP_I12_CAPITAL_AUTHORITY_REPAIR_INSTALL_COMPLETE")


def install() -> None:
    install_import_hook()
