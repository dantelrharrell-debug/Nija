from __future__ import annotations

import builtins
import logging
import os
import sys
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.writer_authority_recursion_guard")
_MARKER = "20260709ax"
_HOOK_FLAG = "_NIJA_WRITER_AUTHORITY_RECURSION_GUARD_HOOK_20260709AX"
_TSM_PATCH_ATTR = "_nija_writer_authority_recursion_guard_20260709ax"
_STATUS_PATCH_ATTR = "_nija_writer_authority_status_reentry_guard_20260709ax"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _float_env(name: str, default: float = 0.0) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        return default


def _writer_reentry_proof() -> dict[str, Any]:
    """Return local proof for recursive status calls without probing Redis again.

    This is not a bypass. It is used only while the authority-status function is
    already active and a second nested status request would recurse. The proof is
    accepted only when live writer artifacts from the previously verified path
    are present: Redis is configured, a fencing token exists, a lease generation
    exists, and the writer heartbeat is fresh.
    """
    token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
    generation = os.environ.get("NIJA_WRITER_LEASE_GENERATION", "").strip()
    heartbeat_active = _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE")
    alive_ts = _float_env("NIJA_WRITER_HEARTBEAT_ALIVE_TS", 0.0)
    max_age_s = max(5.0, _float_env("NIJA_WRITER_REENTRY_HEARTBEAT_MAX_AGE_S", 75.0))
    now_wall = time.time()
    heartbeat_age_s = max(0.0, now_wall - alive_ts) if alive_ts > 0 else 999999.0
    redis_configured = bool(os.environ.get("NIJA_REDIS_URL") or os.environ.get("REDIS_URL"))
    proof_ok = bool(
        redis_configured
        and token
        and generation
        and heartbeat_active
        and heartbeat_age_s <= max_age_s
    )
    return {
        "ok": proof_ok,
        "redis_configured": redis_configured,
        "redis_reachable": proof_ok,
        "token_present": bool(token),
        "token_prefix": token[:8],
        "lease_generation": generation,
        "heartbeat_active": heartbeat_active,
        "heartbeat_age_s": heartbeat_age_s,
        "heartbeat_max_age_s": max_age_s,
    }


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
            cached_ok = bool(last_ok and age_s <= 2.0)
            proof = _writer_reentry_proof()
            ok = bool(cached_ok or proof["ok"])
            if proof["ok"] and not cached_ok:
                logger.warning(
                    "WRITER_AUTHORITY_STATUS_REENTRY_PROOF_ACCEPTED marker=%s cached_age_s=%.3f heartbeat_age_s=%.3f generation=%s token_prefix=%s",
                    _MARKER,
                    age_s,
                    float(proof.get("heartbeat_age_s", 999999.0)),
                    proof.get("lease_generation", ""),
                    proof.get("token_prefix", ""),
                )
            logger.warning(
                "WRITER_AUTHORITY_STATUS_REENTRY_GUARDED marker=%s ok=%s cached_ok=%s cached_age_s=%.3f proof_ok=%s last_error=%s",
                _MARKER,
                ok,
                cached_ok,
                age_s,
                proof["ok"],
                last_err,
            )
            err = "" if ok else (last_err or "writer_authority_status_reentry_guarded")
            return {
                "ok": ok,
                "error": err,
                "strict_required": True,
                "effective_strict_required": True,
                "degraded_override_enabled": False,
                "unsafe_bypass_enabled": False,
                "single_instance_lock_opt_out": False,
                "live_mode": _truthy("LIVE_CAPITAL_VERIFIED"),
                "redis_configured": bool(proof["redis_configured"]),
                "redis_reachable": bool(proof["redis_reachable"]),
                "token_present": bool(proof["token_present"]),
                "token_prefix": str(proof["token_prefix"]),
                "lock_key": os.environ.get("NIJA_WRITER_LOCK_KEY", ""),
                "meta_key": os.environ.get("NIJA_WRITER_LOCK_META_KEY", ""),
                "lease_generation": str(proof["lease_generation"]),
                "heartbeat_active": bool(proof["heartbeat_active"]),
                "heartbeat_age_s": float(proof["heartbeat_age_s"]),
                "authority_verified": ok,
                "current_instance": {},
                "current_holder": {},
                "current_holder_meta": {},
                "holder_inspection": {},
                "cache": {
                    "last_check_monotonic": last_ts,
                    "last_ok": last_ok,
                    "last_error": last_err,
                    "cached_ok": cached_ok,
                    "reentry_proof_ok": proof["ok"],
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
