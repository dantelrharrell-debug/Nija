"""Repair stale authority readiness after LIVE_ACTIVE handoff.

The runtime can reach LIVE_ACTIVE and start TradingLoop while the readiness-table
`authority_ready` bit still reflects an earlier startup snapshot. This module
repairs only that stale bit after the strict runtime writer/nonce checks pass.
It does not change signal thresholds or skip exchange safety checks.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.execution_authority_readiness_repair")
_PATCHED = False
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None


def _truthy(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "enabled", "on"}


def _live_runtime_ready() -> bool:
    return bool(
        _truthy("LIVE_CAPITAL_VERIFIED")
        and not _truthy("DRY_RUN_MODE")
        and not _truthy("PAPER_MODE")
        and os.environ.get("NIJA_RUNTIME_TRADING_STATE", "").strip().upper() == "LIVE_ACTIVE"
        and _truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY")
        and os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
    )


def _kill_switch_clear() -> bool:
    try:
        try:
            from bot.kill_switch import get_kill_switch
        except ImportError:
            from kill_switch import get_kill_switch  # type: ignore[import]
        return not bool(get_kill_switch().is_active())
    except Exception as exc:
        logger.warning("AUTHORITY_READY_REPAIR kill_switch_probe_failed err=%s", exc)
        return False


def _mark_ready() -> None:
    try:
        try:
            from bot.readiness_table import mark_ready
        except ImportError:
            from readiness_table import mark_ready  # type: ignore[import]
        mark_ready("authority_ready")
        logger.critical("AUTHORITY_READY_REPAIR_MARKED_READY")
    except Exception as exc:
        logger.warning("AUTHORITY_READY_REPAIR mark_ready_failed err=%s", exc)


def _install_on_module(tsm: ModuleType) -> bool:
    global _PATCHED
    original = getattr(tsm, "_is_authority_ready", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_authority_ready_repair_wrapped", False):
        _PATCHED = True
        return True

    def _patched_is_authority_ready() -> bool:
        try:
            if bool(original()):
                return True
        except Exception as exc:
            logger.warning("AUTHORITY_READY_REPAIR original_check_failed err=%s", exc)

        if not _live_runtime_ready() or not _kill_switch_clear():
            return False

        strict_probe = getattr(tsm, "_runtime_writer_nonce_ready", None)
        if not callable(strict_probe):
            logger.warning("AUTHORITY_READY_REPAIR strict_probe_missing")
            return False
        try:
            strict_ready, strict_detail = strict_probe()
        except Exception as exc:
            logger.warning("AUTHORITY_READY_REPAIR strict_probe_failed err=%s", exc)
            return False
        if not bool(strict_ready):
            logger.critical("AUTHORITY_READY_REPAIR_WAITING detail=%s", strict_detail or "not_ready")
            return False

        _mark_ready()
        logger.critical(
            "AUTHORITY_READY_REPAIR_APPLIED token_prefix=%s generation=%s",
            os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")[:8],
            os.environ.get("NIJA_WRITER_LEASE_GENERATION", ""),
        )
        return True

    setattr(_patched_is_authority_ready, "_nija_authority_ready_repair_wrapped", True)
    setattr(tsm, "_is_authority_ready", _patched_is_authority_ready)
    _PATCHED = True
    logger.warning("AUTHORITY_READY_REPAIR_PATCHED module=%s", getattr(tsm, "__name__", "<unknown>"))
    return True


def _try_patch_loaded_modules() -> bool:
    patched = False
    for name in ("bot.trading_state_machine", "trading_state_machine"):
        mod = sys.modules.get(name)
        if isinstance(mod, ModuleType):
            patched = _install_on_module(mod) or patched
    return patched


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    _try_patch_loaded_modules()
    if _ORIGINAL_IMPORT_MODULE is not None:
        logger.warning("AUTHORITY_READY_REPAIR_INSTALL_COMPLETE already_installed=True patched=%s", _PATCHED)
        return

    _ORIGINAL_IMPORT_MODULE = importlib.import_module

    def _wrapped_import_module(name: str, package: str | None = None):
        module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
        if name in {"bot.trading_state_machine", "trading_state_machine"}:
            _install_on_module(module)
        return module

    importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
    logger.warning("AUTHORITY_READY_REPAIR_INSTALL_COMPLETE patched=%s", _PATCHED)
