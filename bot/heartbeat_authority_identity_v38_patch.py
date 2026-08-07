"""Canonical heartbeat/authority identity bridge v38.

Repairs a startup-only authority split where ``bot.heartbeat_state`` and the
legacy ``heartbeat_state`` import path can each create their own module-level
singleton.  A writer heartbeat may therefore be successfully renewed and
exported to the environment while an authority reader consults a different,
uninitialised HeartbeatState and reports ``age=inf`` / ``authoritative=False``.

The bridge is installed by the canonical launcher before any ``bot`` import.
It does not acquire authority, refresh Redis, create fencing tokens, or bypass
any gate.  It only makes all heartbeat readers/writers share one process-wide
state object and makes recursive status checks consume that same canonical
monotonic proof plus the already-established entrypoint lease-renewal proof.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Optional

logger = logging.getLogger("nija.heartbeat_authority_identity_v38")
MARKER = "20260807-heartbeat-authority-identity-v38"

_LOCK = threading.RLock()
_INSTALLED = False
_HOOK_FLAG = "_NIJA_HEARTBEAT_AUTHORITY_IDENTITY_V38_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_HEARTBEAT_AUTHORITY_IDENTITY_V38_IMPORTLIB_HOOK"
_STATE_KEY = "_NIJA_CANONICAL_HEARTBEAT_STATE_V38"
_STATE_LOCK_KEY = "_NIJA_CANONICAL_HEARTBEAT_STATE_LOCK_V38"
_HEARTBEAT_PATCHED = "_NIJA_HEARTBEAT_IDENTITY_V38_PATCHED"
_RECURSION_PATCHED = "_NIJA_WRITER_REENTRY_CANONICAL_V38_PATCHED"

_HEARTBEAT_NAMES = ("bot.heartbeat_state", "heartbeat_state")
_RECURSION_NAMES = (
    "bot.writer_authority_recursion_guard_patch",
    "writer_authority_recursion_guard_patch",
)
_ENTRYPOINT_NAMES = ("bot.entrypoint_writer_authority", "entrypoint_writer_authority")
_SINGLE_SOURCE_NAMES = (
    "bot.heartbeat_authority_single_source_patch",
    "heartbeat_authority_single_source_patch",
)


def _shared_lock() -> threading.RLock:
    lock = getattr(builtins, _STATE_LOCK_KEY, None)
    if lock is None:
        with _LOCK:
            lock = getattr(builtins, _STATE_LOCK_KEY, None)
            if lock is None:
                lock = threading.RLock()
                setattr(builtins, _STATE_LOCK_KEY, lock)
    return lock


def _bind_aliases(module: ModuleType) -> None:
    sys.modules["bot.heartbeat_state"] = module
    sys.modules["heartbeat_state"] = module


def _state_score(state: Any) -> tuple[int, float, int]:
    if state is None:
        return (0, 0.0, 0)
    try:
        snap = state.snapshot()
        ts = float(getattr(snap, "timestamp", 0.0) or 0.0)
        generation = int(getattr(snap, "generation", 0) or 0)
        healthy = 1 if bool(getattr(snap, "healthy", False)) else 0
        return (healthy, ts, generation)
    except Exception:
        return (0, 0.0, 0)


def _patch_heartbeat_state(module: ModuleType) -> bool:
    if getattr(module, _HEARTBEAT_PATCHED, False):
        _bind_aliases(module)
        return True

    state_cls = getattr(module, "HeartbeatState", None)
    if not isinstance(state_cls, type):
        return False

    existing_local = getattr(module, "_SINGLETON", None)
    with _shared_lock():
        shared = getattr(builtins, _STATE_KEY, None)
        if shared is None or _state_score(existing_local) > _state_score(shared):
            shared = existing_local if existing_local is not None else state_cls()
            setattr(builtins, _STATE_KEY, shared)

    def get_heartbeat_state() -> Any:
        with _shared_lock():
            state = getattr(builtins, _STATE_KEY, None)
            if state is None:
                state = state_cls()
                setattr(builtins, _STATE_KEY, state)
            module._SINGLETON = state
            return state

    def reset_heartbeat_state_for_testing() -> Any:
        with _shared_lock():
            state = state_cls()
            setattr(builtins, _STATE_KEY, state)
            module._SINGLETON = state
            return state

    module.get_heartbeat_state = get_heartbeat_state
    module.reset_heartbeat_state_for_testing = reset_heartbeat_state_for_testing
    module._SINGLETON = get_heartbeat_state()
    setattr(module, _HEARTBEAT_PATCHED, True)
    _bind_aliases(module)

    logger.critical(
        "HEARTBEAT_STATE_IDENTITY_V38_PATCHED marker=%s module=%s shared_state_id=%s aliases_same=true",
        MARKER,
        module.__name__,
        hex(id(module._SINGLETON)),
    )
    return True


def _canonical_heartbeat_proof(generation: int) -> dict[str, Any]:
    max_age_s = 120.0
    try:
        max_age_s = max(
            5.0,
            float(os.environ.get("NIJA_WRITER_HEARTBEAT_MAX_AGE_S", "120") or 120.0),
        )
    except (TypeError, ValueError):
        pass

    for name in _SINGLE_SOURCE_NAMES:
        module = sys.modules.get(name)
        getter = getattr(module, "heartbeat_max_age_s", None) if isinstance(module, ModuleType) else None
        if callable(getter):
            try:
                max_age_s = max(5.0, float(getter()))
            except Exception:
                pass
            break

    state_module = sys.modules.get("bot.heartbeat_state") or sys.modules.get("heartbeat_state")
    getter = getattr(state_module, "get_heartbeat_state", None) if isinstance(state_module, ModuleType) else None
    if not callable(getter):
        return {
            "healthy": False,
            "authoritative": False,
            "age_s": float("inf"),
            "heartbeat_ts": 0.0,
            "max_age_s": max_age_s,
        }
    try:
        healthy, age_s, authoritative, heartbeat_ts = getter().health_for_generation(
            expected_generation=int(generation or 0),
            max_age_s=max_age_s,
        )
        return {
            "healthy": bool(healthy),
            "authoritative": bool(authoritative),
            "age_s": float(age_s),
            "heartbeat_ts": float(heartbeat_ts or 0.0),
            "max_age_s": max_age_s,
        }
    except Exception as exc:
        logger.warning("HEARTBEAT_STATE_IDENTITY_V38_READ_FAILED marker=%s error=%s", MARKER, exc)
        return {
            "healthy": False,
            "authoritative": False,
            "age_s": float("inf"),
            "heartbeat_ts": 0.0,
            "max_age_s": max_age_s,
        }


def _entrypoint_renewal_proof() -> dict[str, Any]:
    for name in _ENTRYPOINT_NAMES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        getter = getattr(module, "get_entrypoint_writer_authority", None)
        if not callable(getter):
            continue
        try:
            runtime = getter()
        except Exception as exc:
            return {"ok": False, "reason": f"runtime_getter_error:{type(exc).__name__}:{exc}"}
        if runtime is None:
            return {"ok": False, "reason": "runtime_missing"}
        if not bool(getattr(runtime, "acquired", False)):
            return {"ok": False, "reason": "runtime_not_acquired"}
        if bool(getattr(runtime, "lost", False)):
            return {"ok": False, "reason": "runtime_lost"}
        health = getattr(runtime, "_nija_lease_renewal_health", None)
        if not callable(health):
            return {"ok": False, "reason": "renewal_proof_unavailable"}
        try:
            ok, reason, age_s, max_age_s = health()
            return {
                "ok": bool(ok),
                "reason": str(reason or ""),
                "age_s": float(age_s),
                "max_age_s": float(max_age_s),
            }
        except Exception as exc:
            return {"ok": False, "reason": f"renewal_check_error:{type(exc).__name__}:{exc}"}
    return {"ok": False, "reason": "entrypoint_writer_module_unavailable"}


def _patch_recursion_guard(module: ModuleType) -> bool:
    if getattr(module, _RECURSION_PATCHED, False):
        return True
    original = getattr(module, "_writer_reentry_proof", None)
    if not callable(original):
        return False

    def _writer_reentry_proof() -> dict[str, Any]:
        token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
        generation_text = str(
            os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")
            or os.environ.get("NIJA_WRITER_GENERATION", "")
            or ""
        ).strip()
        try:
            generation = int(generation_text or "0")
        except (TypeError, ValueError):
            generation = 0
        heartbeat_active = str(os.environ.get("NIJA_WRITER_HEARTBEAT_ACTIVE", "") or "").strip().lower() in {
            "1", "true", "yes", "on", "enabled", "y"
        }
        redis_configured = bool(
            str(os.environ.get("NIJA_REDIS_URL", "") or "").strip()
            or str(os.environ.get("REDIS_URL", "") or "").strip()
        )
        heartbeat = _canonical_heartbeat_proof(generation)
        renewal = _entrypoint_renewal_proof()

        proof_ok = bool(
            redis_configured
            and token
            and generation > 0
            and heartbeat_active
            and heartbeat.get("healthy")
            and heartbeat.get("authoritative")
            and renewal.get("ok")
        )
        redis_reachable = bool(redis_configured and renewal.get("ok"))

        logger.info(
            "WRITER_AUTHORITY_REENTRY_CANONICAL_PROOF marker=%s ok=%s redis_reachable=%s generation=%s heartbeat_healthy=%s heartbeat_authoritative=%s heartbeat_age_s=%s renewal_ok=%s renewal_reason=%s",
            MARKER,
            proof_ok,
            redis_reachable,
            generation,
            heartbeat.get("healthy"),
            heartbeat.get("authoritative"),
            heartbeat.get("age_s"),
            renewal.get("ok"),
            renewal.get("reason", ""),
        )
        return {
            "ok": proof_ok,
            "redis_configured": redis_configured,
            "redis_reachable": redis_reachable,
            "token_present": bool(token),
            "token_prefix": token[:8],
            "lease_generation": generation_text,
            "heartbeat_active": heartbeat_active,
            "heartbeat_age_s": float(heartbeat.get("age_s", float("inf"))),
            "heartbeat_max_age_s": float(heartbeat.get("max_age_s", 120.0)),
            "heartbeat_authoritative": bool(heartbeat.get("authoritative")),
            "heartbeat_healthy": bool(heartbeat.get("healthy")),
            "renewal_ok": bool(renewal.get("ok")),
            "renewal_reason": str(renewal.get("reason", "")),
        }

    module._writer_reentry_proof = _writer_reentry_proof
    setattr(module, _RECURSION_PATCHED, True)
    logger.critical(
        "WRITER_AUTHORITY_REENTRY_CANONICAL_V38_PATCHED marker=%s module=%s",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in _HEARTBEAT_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_heartbeat_state(module) or changed
    seen.clear()
    for name in _RECURSION_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_recursion_guard(module) or changed
    return changed


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                module = original_import(name, globals, locals, fromlist, level)
                text = str(name)
                if text.endswith("heartbeat_state") or text.endswith("writer_authority_recursion_guard_patch"):
                    _patch_loaded()
                return module

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module(name: str, package: Optional[str] = None):
                module = original_import_module(name, package)
                text = str(name)
                if text.endswith("heartbeat_state") or text.endswith("writer_authority_recursion_guard_patch"):
                    _patch_loaded()
                return module

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        _INSTALLED = True
        os.environ["NIJA_HEARTBEAT_AUTHORITY_IDENTITY_V38_INSTALLED"] = "1"
        logger.critical(
            "HEARTBEAT_AUTHORITY_IDENTITY_V38_INSTALLED marker=%s preboot=true fail_closed=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_patch_heartbeat_state",
    "_patch_recursion_guard",
    "_canonical_heartbeat_proof",
    "_entrypoint_renewal_proof",
]
