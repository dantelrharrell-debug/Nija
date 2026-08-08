"""NIJA heartbeat authority re-anchor v42.

Production after v41 exposed a writer-authority split that can survive even
when the process still owns the Redis writer lease.  The canonical heartbeat
state may retain an older generation or lose its process-local monotonic
freshness origin while environment telemetry still exposes a non-zero epoch
heartbeat timestamp.  Readers then report ``age=inf`` and
``authoritative=False`` and bootstrap remains fail-closed in
``THREADS_STARTING``.

v42 does not trust environment timestamps as authority.  It may repair the
canonical heartbeat only after independently proving all of the following:

* the canonical EntrypointWriterAuthority singleton is acquired and not lost;
* its generation and fencing token match the current environment;
* the lease-renewal worker has a recent successful Redis renewal;
* Redis currently stores the exact writer lock value owned by this runtime;
* the Redis lease-generation key equals the same expected generation; and
* the writer lock still has a positive TTL.

If the renewal worker is missing or dead, v42 may restart that existing
canonical worker once.  The restarted worker still executes the normal v19
lock-owner precheck and all existing fail-closed heartbeat logic.  v42 never
creates, extends, or rewrites the Redis writer lock itself.

If any proof is unavailable, stale, mismatched, or owned by another writer,
the original heartbeat decision is preserved and execution remains blocked.
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

LOGGER = logging.getLogger("nija.heartbeat_authority_reanchor_v42")
MARKER = "20260807-heartbeat-authority-reanchor-v42"

_LOCK = threading.RLock()
_HOOK_FLAG = "_NIJA_HEARTBEAT_AUTHORITY_REANCHOR_V42_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_HEARTBEAT_AUTHORITY_REANCHOR_V42_IMPORTLIB_HOOK"
_SINGLE_SOURCE_PATCH = "_nija_heartbeat_authority_reanchor_v42_single_source"
_V38_PATCH = "_nija_heartbeat_authority_reanchor_v42_v38"
_WRITER_AUTH_PATCH = "_nija_heartbeat_authority_reanchor_v42_writer_authority"
_REENTRY_PATCH = "_nija_heartbeat_authority_reanchor_v42_reentry"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}

_SINGLE_SOURCE_NAMES = (
    "bot.heartbeat_authority_single_source_patch",
    "heartbeat_authority_single_source_patch",
)
_HEARTBEAT_STATE_NAMES = ("bot.heartbeat_state", "heartbeat_state")
_ENTRYPOINT_NAMES = ("bot.entrypoint_writer_authority", "entrypoint_writer_authority")
_V38_NAMES = (
    "bot.heartbeat_authority_identity_v38_patch",
    "heartbeat_authority_identity_v38_patch",
)
_WRITER_AUTHORITY_NAMES = ("bot.writer_authority", "writer_authority")
_REENTRY_NAMES = (
    "bot.writer_authority_recursion_guard_patch",
    "writer_authority_recursion_guard_patch",
)


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _expected_generation() -> int:
    return _as_int(
        os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")
        or os.environ.get("NIJA_WRITER_GENERATION", "")
        or "0"
    )


def _heartbeat_state() -> Any:
    for name in _HEARTBEAT_STATE_NAMES:
        module = sys.modules.get(name)
        getter = getattr(module, "get_heartbeat_state", None) if isinstance(module, ModuleType) else None
        if callable(getter):
            try:
                return getter()
            except Exception:
                continue
    return None


def _entrypoint_runtime() -> tuple[Any, str]:
    seen: set[int] = set()
    for name in _ENTRYPOINT_NAMES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        getter = getattr(module, "get_entrypoint_writer_authority", None)
        if not callable(getter):
            continue
        try:
            runtime = getter()
        except Exception as exc:
            return None, f"runtime_getter_error:{type(exc).__name__}:{exc}"
        if runtime is not None:
            return runtime, ""
    return None, "entrypoint_runtime_unavailable"


def _renewal_health(runtime: Any) -> tuple[bool, str, float, float]:
    health = getattr(runtime, "_nija_lease_renewal_health", None)
    if not callable(health):
        return False, "renewal_health_unavailable", float("inf"), 0.0
    try:
        ok, reason, age_s, max_age_s = health()
        return bool(ok), str(reason or ""), float(age_s), float(max_age_s)
    except Exception as exc:
        return False, f"renewal_health_error:{type(exc).__name__}:{exc}", float("inf"), 0.0


def _restart_dead_renewal_worker(runtime: Any, reason: str) -> bool:
    if reason not in {
        "renewal_thread_missing",
        "renewal_thread_not_alive",
        "renewal_success_uninitialized",
    }:
        return False
    if bool(getattr(runtime, "lost", False)) or not bool(getattr(runtime, "acquired", False)):
        return False
    stop_event = getattr(runtime, "_stop", None)
    if stop_event is not None and callable(getattr(stop_event, "is_set", None)):
        try:
            if stop_event.is_set():
                return False
        except Exception:
            return False
    starter = getattr(runtime, "_start_heartbeat", None)
    if not callable(starter):
        return False
    try:
        starter()
    except Exception as exc:
        LOGGER.warning(
            "HEARTBEAT_V42_RENEWAL_RESTART_FAILED marker=%s generation=%s reason=%s err=%s",
            MARKER,
            getattr(runtime, "_generation", 0),
            reason,
            exc,
        )
        return False

    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        ok, new_reason, _age_s, _max_age_s = _renewal_health(runtime)
        if ok:
            LOGGER.critical(
                "HEARTBEAT_V42_RENEWAL_RESTARTED marker=%s generation=%s previous_reason=%s",
                MARKER,
                getattr(runtime, "_generation", 0),
                reason,
            )
            return True
        if new_reason not in {
            "renewal_thread_missing",
            "renewal_thread_not_alive",
            "renewal_success_uninitialized",
        }:
            return False
        time.sleep(0.05)
    return False


def _redis_lineage_proof(expected_generation: int) -> dict[str, Any]:
    proof: dict[str, Any] = {
        "ok": False,
        "reason": "uninitialized",
        "expected_generation": int(expected_generation or 0),
        "runtime_generation": 0,
        "renewal_ok": False,
        "renewal_reason": "",
        "renewal_age_s": float("inf"),
        "renewal_max_age_s": 0.0,
        "lock_pttl_ms": -2,
    }
    if expected_generation <= 0:
        proof["reason"] = "expected_generation_missing"
        return proof
    if not _truthy("NIJA_WRITER_LEASE_ACQUIRED"):
        proof["reason"] = "lease_flag_not_acquired"
        return proof
    if not _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE"):
        proof["reason"] = "heartbeat_flag_inactive"
        return proof

    runtime, runtime_error = _entrypoint_runtime()
    if runtime is None:
        proof["reason"] = runtime_error
        return proof
    if bool(getattr(runtime, "_local_fallback", False)):
        proof["reason"] = "local_fallback_not_redis_proven"
        return proof
    if not bool(getattr(runtime, "acquired", False)):
        proof["reason"] = "runtime_not_acquired"
        return proof
    if bool(getattr(runtime, "lost", False)):
        proof["reason"] = "runtime_lost"
        return proof

    runtime_generation = _as_int(getattr(runtime, "_generation", 0))
    proof["runtime_generation"] = runtime_generation
    if runtime_generation != expected_generation:
        proof["reason"] = f"runtime_generation_mismatch:{runtime_generation}!={expected_generation}"
        return proof

    runtime_token = str(getattr(runtime, "_token", "") or "").strip()
    env_token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    if not runtime_token or not env_token or runtime_token != env_token:
        proof["reason"] = "fencing_token_mismatch"
        return proof

    renewal_ok, renewal_reason, renewal_age_s, renewal_max_age_s = _renewal_health(runtime)
    if not renewal_ok and _restart_dead_renewal_worker(runtime, renewal_reason):
        renewal_ok, renewal_reason, renewal_age_s, renewal_max_age_s = _renewal_health(runtime)
    proof.update(
        {
            "renewal_ok": bool(renewal_ok),
            "renewal_reason": renewal_reason,
            "renewal_age_s": renewal_age_s,
            "renewal_max_age_s": renewal_max_age_s,
        }
    )
    if not renewal_ok:
        proof["reason"] = f"renewal_not_healthy:{renewal_reason}"
        return proof

    client = getattr(runtime, "_client", None)
    lock_key = str(getattr(runtime, "_lock_key", "") or "").strip()
    lock_value = str(getattr(runtime, "_lock_value", "") or "").strip()
    if client is None or not lock_key or not lock_value:
        proof["reason"] = "redis_runtime_fields_missing"
        return proof

    generation_key = str(
        os.environ.get("NIJA_LEASE_GENERATION_KEY", "") or "nija:lease:generation"
    ).strip()
    try:
        current_lock = _as_text(client.get(lock_key)).strip()
        current_generation = _as_int(client.get(generation_key), default=0)
        pttl_fn = getattr(client, "pttl", None)
        if not callable(pttl_fn):
            proof["reason"] = "redis_pttl_unavailable"
            return proof
        lock_pttl_ms = _as_int(pttl_fn(lock_key), default=-2)
    except Exception as exc:
        proof["reason"] = f"redis_lineage_read_error:{type(exc).__name__}:{exc}"
        return proof

    proof["lock_pttl_ms"] = lock_pttl_ms
    proof["redis_generation"] = current_generation
    if current_lock != lock_value:
        proof["reason"] = "redis_lock_not_owned_exactly"
        return proof
    if current_generation != expected_generation:
        proof["reason"] = f"redis_generation_mismatch:{current_generation}!={expected_generation}"
        return proof
    if lock_pttl_ms <= 0:
        proof["reason"] = f"redis_lock_ttl_not_positive:{lock_pttl_ms}"
        return proof

    proof["ok"] = True
    proof["reason"] = "exact_redis_lineage_and_fresh_renewal"
    proof["runtime"] = runtime
    return proof


def _single_source_module() -> Optional[ModuleType]:
    seen: set[int] = set()
    for name in _SINGLE_SOURCE_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            return module
    return None


def _attempt_reanchor(source: str) -> tuple[bool, dict[str, Any]]:
    with _LOCK:
        expected_generation = _expected_generation()
        state = _heartbeat_state()
        if state is None:
            return False, {"reason": "heartbeat_state_unavailable"}
        try:
            snapshot = state.snapshot()
            state_generation = _as_int(getattr(snapshot, "generation", 0))
            state_timestamp = float(getattr(snapshot, "timestamp", 0.0) or 0.0)
        except Exception as exc:
            return False, {"reason": f"heartbeat_snapshot_error:{type(exc).__name__}:{exc}"}

        if state_generation > expected_generation > 0:
            return False, {
                "reason": "canonical_generation_newer_than_expected",
                "state_generation": state_generation,
                "expected_generation": expected_generation,
            }

        proof = _redis_lineage_proof(expected_generation)
        proof["state_generation"] = state_generation
        proof["state_timestamp"] = state_timestamp
        if not proof.get("ok"):
            return False, proof

        single_source = _single_source_module()
        refresh = getattr(single_source, "refresh_heartbeat", None) if single_source else None
        if not callable(refresh):
            proof["reason"] = "single_source_refresh_unavailable"
            proof["ok"] = False
            return False, proof
        try:
            refreshed_ts = float(
                refresh(
                    source=f"heartbeat_authority_reanchor_v42:{source}",
                    generation=expected_generation,
                )
                or 0.0
            )
        except Exception as exc:
            proof["reason"] = f"canonical_refresh_failed:{type(exc).__name__}:{exc}"
            proof["ok"] = False
            return False, proof
        if refreshed_ts <= 0.0:
            proof["reason"] = "canonical_refresh_returned_zero"
            proof["ok"] = False
            return False, proof

        proof["refreshed_ts"] = refreshed_ts
        proof["reason"] = "canonical_heartbeat_reanchored"
        return True, proof


def _patch_single_source(module: ModuleType) -> bool:
    if getattr(module, _SINGLE_SOURCE_PATCH, False):
        return True
    original = getattr(module, "heartbeat_check", None)
    if not callable(original):
        return False

    @wraps(original)
    def heartbeat_check(*, source: str):
        result = original(source=source)
        try:
            healthy, _now, _heartbeat_ts, age_s, authoritative = result
        except Exception:
            return result
        if bool(healthy) and bool(authoritative):
            return result

        repaired, proof = _attempt_reanchor(source)
        if not repaired:
            LOGGER.warning(
                "HEARTBEAT_V42_REANCHOR_BLOCKED marker=%s source=%s reason=%s expected_generation=%s state_generation=%s renewal_reason=%s",
                MARKER,
                source,
                proof.get("reason", "unknown"),
                proof.get("expected_generation", _expected_generation()),
                proof.get("state_generation", "unknown"),
                proof.get("renewal_reason", ""),
            )
            return result

        repaired_result = original(source=source)
        try:
            repaired_healthy, _repaired_now, repaired_ts, repaired_age_s, repaired_authoritative = repaired_result
        except Exception:
            return repaired_result
        LOGGER.critical(
            "HEARTBEAT_V42_REANCHORED marker=%s source=%s generation=%s previous_age_s=%s previous_authoritative=%s repaired_ts=%.6f repaired_age_s=%.3f repaired_healthy=%s repaired_authoritative=%s lock_pttl_ms=%s renewal_age_s=%.3f",
            MARKER,
            source,
            proof.get("expected_generation", 0),
            age_s,
            authoritative,
            float(repaired_ts or 0.0),
            float(repaired_age_s),
            bool(repaired_healthy),
            bool(repaired_authoritative),
            proof.get("lock_pttl_ms", -2),
            float(proof.get("renewal_age_s", 0.0) or 0.0),
        )
        return repaired_result

    module.heartbeat_check = heartbeat_check
    setattr(module, _SINGLE_SOURCE_PATCH, True)
    LOGGER.critical(
        "HEARTBEAT_V42_SINGLE_SOURCE_PATCHED marker=%s module=%s",
        MARKER,
        module.__name__,
    )
    return True


def _patch_v38(module: ModuleType) -> bool:
    if getattr(module, _V38_PATCH, False):
        return True
    original = getattr(module, "_canonical_heartbeat_proof", None)
    if not callable(original):
        return False

    @wraps(original)
    def _canonical_heartbeat_proof(generation: int):
        proof = original(generation)
        if bool(proof.get("healthy")) and bool(proof.get("authoritative")):
            return proof
        repaired, _detail = _attempt_reanchor("v38_canonical_heartbeat_proof")
        if repaired:
            return original(generation)
        return proof

    module._canonical_heartbeat_proof = _canonical_heartbeat_proof
    setattr(module, _V38_PATCH, True)
    LOGGER.critical("HEARTBEAT_V42_V38_PATCHED marker=%s module=%s", MARKER, module.__name__)
    return True


def _patch_writer_authority(module: ModuleType) -> bool:
    if getattr(module, _WRITER_AUTH_PATCH, False):
        return True
    original = getattr(module, "_canonical_heartbeat_health", None)
    if not callable(original):
        return False

    @wraps(original)
    def _canonical_heartbeat_health(*, generation: str, max_age_s: float):
        result = original(generation=generation, max_age_s=max_age_s)
        try:
            healthy, _age_s, authoritative = result
        except Exception:
            return result
        if bool(healthy) and bool(authoritative):
            return result
        repaired, _detail = _attempt_reanchor("writer_authority_canonical_health")
        if repaired:
            return original(generation=generation, max_age_s=max_age_s)
        return result

    module._canonical_heartbeat_health = _canonical_heartbeat_health
    setattr(module, _WRITER_AUTH_PATCH, True)
    LOGGER.critical(
        "HEARTBEAT_V42_WRITER_AUTHORITY_PATCHED marker=%s module=%s",
        MARKER,
        module.__name__,
    )
    return True


def _patch_reentry_guard(module: ModuleType) -> bool:
    if getattr(module, _REENTRY_PATCH, False):
        return True
    original = getattr(module, "_writer_reentry_proof", None)
    if not callable(original):
        return False

    @wraps(original)
    def _writer_reentry_proof():
        proof = dict(original() or {})
        if bool(proof.get("ok")):
            return proof
        repaired, _detail = _attempt_reanchor("writer_authority_reentry_guard")
        if repaired:
            return dict(original() or {})
        return proof

    module._writer_reentry_proof = _writer_reentry_proof
    setattr(module, _REENTRY_PATCH, True)
    LOGGER.critical(
        "HEARTBEAT_V42_REENTRY_PATCHED marker=%s module=%s",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    groups = (
        (_SINGLE_SOURCE_NAMES, _patch_single_source),
        (_V38_NAMES, _patch_v38),
        (_WRITER_AUTHORITY_NAMES, _patch_writer_authority),
        (_REENTRY_NAMES, _patch_reentry_guard),
    )
    for names, patcher in groups:
        seen: set[int] = set()
        for name in names:
            module = sys.modules.get(name)
            if not isinstance(module, ModuleType) or id(module) in seen:
                continue
            seen.add(id(module))
            try:
                changed = patcher(module) or changed
            except Exception as exc:
                LOGGER.warning(
                    "HEARTBEAT_V42_PATCH_FAILED marker=%s module=%s err=%s",
                    MARKER,
                    name,
                    exc,
                    exc_info=True,
                )
    return changed


def _interesting(name: str) -> bool:
    text = str(name or "")
    return any(
        text.endswith(suffix)
        for suffix in (
            "heartbeat_authority_single_source_patch",
            "heartbeat_authority_identity_v38_patch",
            "writer_authority",
            "writer_authority_recursion_guard_patch",
            "entrypoint_writer_authority",
            "heartbeat_state",
        )
    )


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if _interesting(name):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module(name: str, package: Optional[str] = None):
                result = original_import_module(name, package)
                if _interesting(name):
                    _patch_loaded()
                return result

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        os.environ["NIJA_HEARTBEAT_AUTHORITY_REANCHOR_V42_INSTALLED"] = "1"
        LOGGER.critical(
            "HEARTBEAT_AUTHORITY_REANCHOR_V42_INSTALLED marker=%s fail_closed=true redis_lock_mutation=false",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_attempt_reanchor",
    "_redis_lineage_proof",
    "_restart_dead_renewal_worker",
]
