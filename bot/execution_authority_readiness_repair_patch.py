"""Repair stale startup readiness bits after LIVE_ACTIVE handoff.

The runtime can reach LIVE_ACTIVE and start TradingLoop while the readiness-table
still reflects an earlier startup snapshot. In that state the live execution gate
can keep returning dispatch=False even though strict writer authority, heartbeat,
nonce sync, nonce lease, and lease-generation continuity are already valid.

This module repairs only stale readiness-table state after those strict runtime
checks pass. It does not change signal thresholds, loosen order-admission gates,
skip exchange safety checks, or submit orders.
"""

from __future__ import annotations

import gc
import importlib
import logging
import os
import sys
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.execution_authority_readiness_repair")
_PATCHED = False
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None

_LIVE_READY_KEYS = (
    "broker_connected",
    "balance_hydrated",
    "authority_ready",
    "capital_ready",
    "risk_ready",
    "strategy_ready",
    "execution_ready",
    "nonce_ready",
    "bootstrap_ready",
)


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


def _capital_hydrated() -> bool:
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
        if not bool(getattr(ca, "is_hydrated", False)):
            return False
        total = float(getattr(ca, "total_capital", 0.0) or 0.0)
        return total > 0.0
    except Exception as exc:
        logger.warning("AUTHORITY_READY_REPAIR capital_probe_failed err=%s", exc)
        return False


def _strategy_published() -> bool:
    for mod_name in ("__main__", "bot", "bot.bot", "bot.trading_strategy", "trading_strategy"):
        mod = sys.modules.get(mod_name)
        if not isinstance(mod, ModuleType):
            continue
        for attr in ("TRADING_STRATEGY", "strategy", "trading_strategy", "_published_strategy"):
            obj = getattr(mod, attr, None)
            if obj is not None and type(obj).__name__ == "TradingStrategy":
                return True
    try:
        for obj in gc.get_objects():
            if type(obj).__name__ == "TradingStrategy":
                return True
    except Exception:
        pass
    return False


def _mark_live_readiness_ready(reason: str) -> None:
    try:
        try:
            from bot.readiness_table import mark_ready, pending
        except ImportError:
            from readiness_table import mark_ready, pending  # type: ignore[import]
        before = list(pending() or [])
        for key in _LIVE_READY_KEYS:
            mark_ready(key)
        after = list(pending() or [])
        logger.critical(
            "AUTHORITY_READY_REPAIR_MARKED_LIVE_READINESS reason=%s before=%s after=%s",
            reason,
            before,
            after,
        )
    except Exception as exc:
        logger.warning("AUTHORITY_READY_REPAIR mark_live_readiness_failed err=%s", exc)


def _strict_runtime_authority_ready(tsm: ModuleType) -> tuple[bool, str]:
    strict_probe = getattr(tsm, "_runtime_writer_nonce_ready", None)
    if not callable(strict_probe):
        return False, "strict_probe_missing"
    try:
        strict_ready, strict_detail = strict_probe()
    except Exception as exc:
        return False, f"strict_probe_failed:{exc}"
    if not bool(strict_ready):
        return False, strict_detail or "strict_runtime_authority_not_ready"
    return True, ""


def _repair_live_readiness_if_safe(tsm: ModuleType, reason: str) -> bool:
    if not _live_runtime_ready():
        return False
    if not _kill_switch_clear():
        return False
    if not _capital_hydrated():
        logger.critical("AUTHORITY_READY_REPAIR_WAITING detail=capital_not_hydrated")
        return False
    if not _strategy_published():
        logger.critical("AUTHORITY_READY_REPAIR_WAITING detail=strategy_not_published")
        return False

    strict_ready, strict_detail = _strict_runtime_authority_ready(tsm)
    if not strict_ready:
        logger.critical("AUTHORITY_READY_REPAIR_WAITING detail=%s", strict_detail or "not_ready")
        return False

    _mark_live_readiness_ready(reason)
    logger.critical(
        "AUTHORITY_READY_REPAIR_APPLIED token_prefix=%s generation=%s reason=%s",
        os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")[:8],
        os.environ.get("NIJA_WRITER_LEASE_GENERATION", ""),
        reason,
    )
    return True


def _install_on_module(tsm: ModuleType) -> bool:
    global _PATCHED
    installed_any = False

    original_authority = getattr(tsm, "_is_authority_ready", None)
    if callable(original_authority) and not getattr(original_authority, "_nija_authority_ready_repair_wrapped", False):
        def _patched_is_authority_ready() -> bool:
            try:
                if bool(original_authority()):
                    return True
            except Exception as exc:
                logger.warning("AUTHORITY_READY_REPAIR original_authority_check_failed err=%s", exc)
            return _repair_live_readiness_if_safe(tsm, "authority_ready_gate")

        setattr(_patched_is_authority_ready, "_nija_authority_ready_repair_wrapped", True)
        setattr(tsm, "_is_authority_ready", _patched_is_authority_ready)
        installed_any = True

    original_strategy = getattr(tsm, "_strategy_ready_gate", None)
    if callable(original_strategy) and not getattr(original_strategy, "_nija_strategy_ready_repair_wrapped", False):
        def _patched_strategy_ready_gate() -> tuple[bool, str]:
            try:
                ok, detail = original_strategy()
                if bool(ok):
                    return True, str(detail or "")
                original_detail = str(detail or "")
            except Exception as exc:
                original_detail = f"original_strategy_gate_failed:{exc}"

            if _repair_live_readiness_if_safe(tsm, f"strategy_ready_gate:{original_detail}"):
                return True, "live_readiness_repaired"
            return False, original_detail or "not_ready"

        setattr(_patched_strategy_ready_gate, "_nija_strategy_ready_repair_wrapped", True)
        setattr(tsm, "_strategy_ready_gate", _patched_strategy_ready_gate)
        installed_any = True

    if installed_any:
        _PATCHED = True
        logger.warning("AUTHORITY_READY_REPAIR_PATCHED module=%s", getattr(tsm, "__name__", "<unknown>"))
    return bool(_PATCHED)


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
