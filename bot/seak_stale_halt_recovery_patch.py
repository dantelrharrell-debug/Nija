from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.seak_stale_halt_recovery")
_PATCHED_ATTR = "_nija_seak_stale_halt_recovery_20260708a"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_RECOVERABLE_TOKENS = (
    "AUTHORITY_HEARTBEAT_EXPIRED",
    "writer_heartbeat_stale",
    "heartbeat_stale",
)


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in _TRUE


def _redis_nonce_heartbeat_alive() -> bool:
    try:
        for thread in threading.enumerate():
            name = str(getattr(thread, "name", "") or "")
            if thread.is_alive() and "RedisNonceLeaseHeartbeat" in name:
                return True
    except Exception:
        pass
    return False


def _seak_halt_reason() -> str:
    try:
        try:
            from bot.single_execution_authority_kernel import get_seak
        except ImportError:
            from single_execution_authority_kernel import get_seak  # type: ignore[import]
        seak = get_seak()
        return str(getattr(seak, "_halt_reason", "") or "")
    except Exception:
        return ""


def _can_recover(ctx: ModuleType, reason: str) -> tuple[bool, str]:
    if not _truthy("NIJA_SEAK_RECOVER_STALE_HEARTBEAT_HALT", "true"):
        return False, "disabled"
    if not _truthy("LIVE_CAPITAL_VERIFIED", "false"):
        return False, "live_capital_not_verified"
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "simulation_mode"
    if not any(token.lower() in reason.lower() for token in _RECOVERABLE_TOKENS):
        return False, f"non_recoverable_halt:{reason or 'unknown'}"
    status_fn = getattr(ctx, "get_distributed_writer_authority_status", None)
    if callable(status_fn):
        try:
            status = status_fn(force_refresh=True)
            if not bool(status.get("ok")):
                return False, f"writer_authority_not_ok:{status.get('error') or 'unknown'}"
        except Exception as exc:
            return False, f"writer_authority_probe_failed:{exc}"
    if not os.getenv("NIJA_WRITER_FENCING_TOKEN", "").strip():
        return False, "writer_token_missing"
    if not _redis_nonce_heartbeat_alive():
        return False, "redis_nonce_heartbeat_not_alive"
    return True, "strict_stale_heartbeat_halt_recoverable"


def _recover(ctx: ModuleType, reason: str) -> bool:
    ok, detail = _can_recover(ctx, reason)
    if not ok:
        logger.warning("SEAK_STALE_HALT_RECOVERY_WAITING marker=20260708a detail=%s reason=%s", detail, reason)
        return False
    try:
        try:
            from bot.single_execution_authority_kernel import get_seak
        except ImportError:
            from single_execution_authority_kernel import get_seak  # type: ignore[import]
        seak = get_seak()
        resume = getattr(seak, "resume", None)
        if callable(resume):
            resume(caller="seak_stale_halt_recovery_20260708a")
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
        now = f"{time.time():.6f}"
        os.environ["NIJA_WRITER_HEARTBEAT_LAST_TS"] = now
        os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = now
        logger.critical("SEAK_STALE_HALT_RECOVERED marker=20260708a reason=%s detail=%s", reason, detail)
        print("[NIJA-PRINT] SEAK_STALE_HALT_RECOVERED marker=20260708a", flush=True)
        return True
    except Exception as exc:
        logger.warning("SEAK_STALE_HALT_RECOVERY_FAILED marker=20260708a err=%s reason=%s", exc, reason)
        return False


def _patch_context(ctx: ModuleType) -> bool:
    original = getattr(ctx, "is_seak_halted", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    def is_seak_halted_recovering() -> bool:
        halted = bool(original())
        if not halted:
            return False
        reason = _seak_halt_reason()
        if _recover(ctx, reason):
            return False
        return True

    setattr(is_seak_halted_recovering, _PATCHED_ATTR, True)
    setattr(ctx, "is_seak_halted", is_seak_halted_recovering)
    logger.warning("SEAK_STALE_HALT_RECOVERY_PATCHED marker=20260708a module=%s", getattr(ctx, "__name__", "unknown"))
    return True


def _patch_loaded() -> None:
    for name in ("bot.execution_authority_context", "execution_authority_context"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_context(module)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, "_NIJA_SEAK_STALE_HALT_RECOVERY_HOOK_20260708A", False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if name in {"bot.execution_authority_context", "execution_authority_context"} or str(name).endswith("execution_authority_context"):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, "_NIJA_SEAK_STALE_HALT_RECOVERY_HOOK_20260708A", True)
    logger.warning("SEAK_STALE_HALT_RECOVERY_INSTALL_COMPLETE marker=20260708a")


def install() -> None:
    install_import_hook()
