from __future__ import annotations

import builtins
import logging
import os
import sys
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.writer_authority_recursion_guard")
_MARKER = "20260709aq"
_HOOK_FLAG = "_NIJA_WRITER_AUTHORITY_RECURSION_GUARD_HOOK_20260709AQ"
_TSM_PATCH_ATTR = "_nija_writer_authority_recursion_guard_20260709aq"
_STATUS_PATCH_ATTR = "_nija_writer_authority_status_reentry_guard_20260709aq"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _patch_execution_authority_context(module: ModuleType) -> bool:
    original = getattr(module, "get_distributed_writer_authority_status", None)
    if not callable(original) or getattr(original, _STATUS_PATCH_ATTR, False):
        return False
    state = {"active": False}

    def guarded_status(force_refresh: bool = False):
        if state["active"]:
            last_ok = bool(getattr(module, "_FENCE_LAST_OK", False))
            last_err = str(getattr(module, "_FENCE_LAST_ERR", "") or "")
            last_ts = float(getattr(module, "_FENCE_LAST_CHECK_TS", 0.0) or 0.0)
            age_s = max(0.0, time.monotonic() - last_ts) if last_ts > 0 else 999999.0
            ok = bool(last_ok and age_s <= 2.0)
            logger.warning(
                "WRITER_AUTHORITY_STATUS_REENTRY_GUARDED marker=%s ok=%s cached_age_s=%.3f last_error=%s",
                _MARKER,
                ok,
                age_s,
                last_err,
            )
            return {
                "ok": ok,
                "error": "" if ok else (last_err or "writer_authority_status_reentry_guarded"),
                "strict_required": True,
                "effective_strict_required": True,
                "degraded_override_enabled": False,
                "unsafe_bypass_enabled": False,
                "single_instance_lock_opt_out": False,
                "live_mode": _truthy("LIVE_CAPITAL_VERIFIED"),
                "redis_configured": bool(os.environ.get("NIJA_REDIS_URL") or os.environ.get("REDIS_URL")),
                "redis_reachable": False,
                "token_present": bool(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()),
                "token_prefix": os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()[:8],
                "lock_key": os.environ.get("NIJA_WRITER_LOCK_KEY", ""),
                "meta_key": os.environ.get("NIJA_WRITER_LOCK_META_KEY", ""),
                "current_instance": {},
                "current_holder": {},
                "current_holder_meta": {},
                "holder_inspection": {},
                "cache": {
                    "last_check_monotonic": last_ts,
                    "last_ok": last_ok,
                    "last_error": last_err,
                },
            }
        state["active"] = True
        try:
            return original(force_refresh=force_refresh)
        finally:
            state["active"] = False

    setattr(guarded_status, _STATUS_PATCH_ATTR, True)
    setattr(module, "get_distributed_writer_authority_status", guarded_status)
    logger.warning("WRITER_AUTHORITY_STATUS_REENTRY_GUARD_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    return True


def _patch_trading_state_machine(module: ModuleType) -> bool:
    if getattr(module, _TSM_PATCH_ATTR, False):
        return False
    resolve_token = getattr(module, "_resolve_writer_fencing_token", None)
    if not callable(resolve_token):
        return False

    def distributed_writer_authority_gate_guarded() -> tuple[bool, str]:
        local_fallback = _truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK")
        writer_lease_manager = None
        try:
            try:
                from bot.distributed_nonce_manager import get_distributed_nonce_manager
            except ImportError:
                from distributed_nonce_manager import get_distributed_nonce_manager  # type: ignore[import]
            writer_lease_manager = get_distributed_nonce_manager()
        except Exception:
            writer_lease_manager = None

        fencing_token = str(resolve_token(writer_lease_manager) or "").strip()
        if not fencing_token:
            if local_fallback:
                logger.warning(
                    "WRITER_AUTHORITY_RECURSION_GUARD_LOCAL_FALLBACK marker=%s reason=missing_fencing_token",
                    _MARKER,
                )
            else:
                err = (
                    "LIVE TRADING BLOCKED: NIJA_WRITER_FENCING_TOKEN is not set. "
                    "Redis distributed writer authority is required for LIVE_ACTIVE. "
                    "Ensure the bot acquired a Redis writer lease at startup."
                )
                logger.critical("[WRITER AUTHORITY HARD FAIL] %s", err)
                return False, err

        retries = max(1, int(os.environ.get("NIJA_REDIS_LOCK_RETRIES", "3") or "3"))
        retry_delay_s = max(0.0, float(os.environ.get("NIJA_REDIS_LOCK_RETRY_DELAY_S", "0.20") or "0.20"))
        last_err = ""
        for attempt in range(retries):
            try:
                try:
                    from bot.execution_authority_context import assert_distributed_writer_authority
                except ImportError:
                    from execution_authority_context import assert_distributed_writer_authority  # type: ignore[import]
                assert_distributed_writer_authority()
                logger.info("WRITER_AUTHORITY_RECURSION_GUARD_VERIFIED marker=%s attempt=%d", _MARKER, attempt + 1)
                return True, ""
            except RecursionError as exc:
                last_err = f"writer_authority_recursion_guarded:{exc}"
                break
            except Exception as exc:
                last_err = str(exc)
                if attempt < retries - 1 and retry_delay_s > 0:
                    time.sleep(retry_delay_s)

        if local_fallback:
            logger.warning(
                "[WRITER AUTHORITY] distributed authority verification failed after %d attempt(s) but local fallback is enabled. last_error=%s",
                retries,
                last_err,
            )
            return True, ""

        err = (
            "LIVE TRADING BLOCKED: distributed writer authority verification failed "
            f"after {retries} attempt(s). Redis must be reachable and fencing token "
            f"must be valid before LIVE_ACTIVE is permitted. last_error={last_err}"
        )
        logger.critical("[WRITER AUTHORITY HARD FAIL] %s", err)
        return False, err

    setattr(module, "_distributed_writer_authority_gate", distributed_writer_authority_gate_guarded)
    setattr(module, _TSM_PATCH_ATTR, True)
    logger.warning("WRITER_AUTHORITY_RECURSION_GUARD_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    print(f"[NIJA-PRINT] WRITER_AUTHORITY_RECURSION_GUARD_PATCHED marker={_MARKER}", flush=True)
    return True


def _patch_loaded() -> None:
    for name in ("bot.execution_authority_context", "execution_authority_context"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_execution_authority_context(module)
            except Exception as exc:
                logger.warning("WRITER_AUTHORITY_STATUS_REENTRY_GUARD_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    for name in ("bot.trading_state_machine", "trading_state_machine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_trading_state_machine(module)
            except Exception as exc:
                logger.warning("WRITER_AUTHORITY_RECURSION_GUARD_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, _HOOK_FLAG, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        text = str(name)
        if text.endswith("execution_authority_context") or text.endswith("trading_state_machine"):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _HOOK_FLAG, True)
    logger.warning("WRITER_AUTHORITY_RECURSION_GUARD_INSTALL_COMPLETE marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
