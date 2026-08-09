"""Writer authority reconstitution v77.

Production after the v59 hardening showed a circular recovery failure: Redis and
the canonical EntrypointWriterAuthority could still describe the current writer
lineage while process-local environment aliases had fallen back to generation 0
/ missing lease flags.  v42 correctly refused to re-anchor because its expected
generation is sourced from those local aliases.

v77 breaks that loop without trusting Redis generation by itself.

Safe paths
----------
1. Exact-owner reconstitution: only when the canonical EntrypointWriterAuthority
   runtime is acquired/not-lost and Redis proves the runtime's exact lock value,
   fencing generation and positive TTL do we republish process-local aliases.
2. Bounded reacquisition: if exact-owner proof is unavailable, delegate to the
   existing canonical ``_acquire_writer_authority_before_nonce`` path.  That
   path remains responsible for lock acquisition/fencing and can fail closed.

v77 never rewrites the Redis lock, never copies a foreign Redis generation into
local state, and never clears kill-switch/risk/readiness gates.
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

LOGGER = logging.getLogger("nija.writer_authority_reconstitution_v77")
MARKER = "20260809-writer-authority-reconstitution-v77"
_LOCK = threading.RLock()
_PATCH_ATTR = "_nija_writer_authority_reconstitution_v77"
_HOOK_FLAG = "_NIJA_WRITER_AUTHORITY_RECONSTITUTION_V77_IMPORT_HOOK"
_ENTRYPOINT_NAMES = ("bot.entrypoint_writer_authority", "entrypoint_writer_authority")
_V42_NAMES = (
    "nija_heartbeat_authority_reanchor_v42_prebot",
    "bot.heartbeat_authority_reanchor_v42_patch",
    "heartbeat_authority_reanchor_v42_patch",
)
_SINGLE_SOURCE_NAMES = (
    "bot.heartbeat_authority_single_source_patch",
    "heartbeat_authority_single_source_patch",
)


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _runtime() -> tuple[Any, str]:
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


def _generation_key() -> str:
    return str(os.environ.get("NIJA_LEASE_GENERATION_KEY", "") or "nija:lease:generation").strip()


def exact_owner_proof(runtime: Any = None) -> tuple[Optional[dict[str, Any]], str]:
    """Prove canonical runtime ownership without relying on local env aliases."""
    if runtime is None:
        runtime, error = _runtime()
        if runtime is None:
            return None, error
    if bool(getattr(runtime, "_local_fallback", False)):
        return None, "local_fallback_rejected"
    if not bool(getattr(runtime, "acquired", False)):
        return None, "runtime_not_acquired"
    if bool(getattr(runtime, "lost", False)):
        return None, "runtime_marked_lost"

    generation = _integer(getattr(runtime, "_generation", 0))
    token = str(getattr(runtime, "_token", "") or "").strip()
    lock_key = str(getattr(runtime, "_lock_key", "") or "").strip()
    lock_value = str(getattr(runtime, "_lock_value", "") or "").strip()
    client = getattr(runtime, "_client", None)
    if generation <= 0:
        return None, "runtime_generation_missing"
    if not token:
        return None, "runtime_fencing_token_missing"
    if client is None or not lock_key or not lock_value:
        return None, "runtime_redis_identity_missing"

    try:
        redis_lock = _text(client.get(lock_key)).strip()
        redis_generation = _integer(client.get(_generation_key()), 0)
        pttl = _integer(client.pttl(lock_key), -2)
    except Exception as exc:
        return None, f"redis_proof_error:{type(exc).__name__}:{exc}"

    if redis_lock != lock_value:
        return None, "redis_lock_owner_mismatch" if redis_lock else "redis_lock_missing"
    if redis_generation != generation:
        return None, f"redis_generation_mismatch:{redis_generation}!={generation}"
    if pttl <= 0:
        return None, f"redis_lock_ttl_not_positive:{pttl}"

    return {
        "runtime": runtime,
        "generation": generation,
        "token": token,
        "lock_key": lock_key,
        "lock_value": lock_value,
        "pttl_ms": pttl,
    }, "exact_runtime_redis_owner"


def _ensure_renewal_worker(runtime: Any) -> None:
    health = getattr(runtime, "_nija_lease_renewal_health", None)
    starter = getattr(runtime, "_start_heartbeat", None)
    if not callable(health) or not callable(starter):
        return
    try:
        ok, reason, _age, _limit = health()
    except Exception:
        return
    if ok or str(reason or "") not in {
        "renewal_thread_missing",
        "renewal_thread_not_alive",
        "renewal_success_uninitialized",
    }:
        return
    try:
        starter()
    except Exception as exc:
        LOGGER.warning(
            "WRITER_V77_RENEWAL_RESTART_FAILED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )


def _refresh_canonical_heartbeat(generation: int, source: str) -> bool:
    for name in _SINGLE_SOURCE_NAMES:
        module = sys.modules.get(name)
        refresh = getattr(module, "refresh_heartbeat", None) if isinstance(module, ModuleType) else None
        if not callable(refresh):
            continue
        try:
            return float(refresh(source=f"writer_v77:{source}", generation=generation) or 0.0) > 0.0
        except Exception:
            return False
    return False


def publish_local_lineage(proof: dict[str, Any], source: str) -> tuple[bool, int, str]:
    """Republish process-local aliases after exact owner proof only."""
    generation = int(proof["generation"])
    token = str(proof["token"])
    runtime = proof["runtime"]
    before = {
        "lease_flag": os.environ.get("NIJA_WRITER_LEASE_ACQUIRED", ""),
        "lease_generation": os.environ.get("NIJA_WRITER_LEASE_GENERATION", ""),
        "generation": os.environ.get("NIJA_WRITER_GENERATION", ""),
        "token": os.environ.get("NIJA_WRITER_FENCING_TOKEN", ""),
    }
    value = str(generation)
    os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"
    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
    os.environ["NIJA_WRITER_LEASE_GENERATION"] = value
    os.environ["NIJA_WRITER_GENERATION"] = value
    os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = value
    os.environ["NIJA_WRITER_LEASE_GENERATION_EXPECTED"] = value
    os.environ["NIJA_WRITER_FENCING_TOKEN"] = token
    _ensure_renewal_worker(runtime)
    heartbeat_refreshed = _refresh_canonical_heartbeat(generation, source)
    LOGGER.critical(
        "WRITER_V77_LOCAL_LINEAGE_RECONSTITUTED marker=%s source=%s generation=%d "
        "pttl_ms=%s redis_mutation=false exact_owner=true heartbeat_refreshed=%s before=%s",
        MARKER,
        source,
        generation,
        proof.get("pttl_ms", -2),
        str(heartbeat_refreshed).lower(),
        before,
    )
    return True, generation, "exact_owner_reconstituted"


def _canonical_reacquire(source: str) -> tuple[bool, int, str]:
    """Delegate fresh acquisition to the existing canonical writer bootstrap."""
    try:
        bot_main = importlib.import_module("bot.bot_main")
    except Exception as exc:
        return False, 0, f"bot_main_import_error:{type(exc).__name__}:{exc}"
    acquire = getattr(bot_main, "_acquire_writer_authority_before_nonce", None)
    if not callable(acquire):
        return False, 0, "canonical_acquire_unavailable"
    try:
        acquired = bool(acquire())
    except Exception as exc:
        return False, 0, f"canonical_acquire_error:{type(exc).__name__}:{exc}"
    if not acquired:
        return False, 0, str(getattr(bot_main, "_writer_authority_last_error", "") or "canonical_acquire_failed")

    runtime = getattr(bot_main, "_writer_authority_runtime", None)
    proof, reason = exact_owner_proof(runtime)
    if proof is None:
        return False, 0, f"post_acquire_proof_failed:{reason}"
    LOGGER.critical(
        "WRITER_V77_FRESH_REACQUISITION_PROVEN marker=%s source=%s generation=%s pttl_ms=%s",
        MARKER,
        source,
        proof["generation"],
        proof["pttl_ms"],
    )
    return publish_local_lineage(proof, f"{source}:fresh_reacquire")


def repair_or_reacquire(source: str = "runtime") -> tuple[bool, int, str]:
    """Restore local identity from proof, otherwise use bounded canonical acquisition."""
    with _LOCK:
        proof, reason = exact_owner_proof()
        if proof is not None:
            return publish_local_lineage(proof, source)
        LOGGER.warning(
            "WRITER_V77_EXACT_OWNER_PROOF_UNAVAILABLE marker=%s source=%s reason=%s action=canonical_reacquire",
            MARKER,
            source,
            reason,
        )
        return _canonical_reacquire(source)


def _patch_v42(module: ModuleType) -> bool:
    current = getattr(module, "_attempt_reanchor", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def attempt_reanchor_v77(source: str):
        expected = _integer(
            os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")
            or os.environ.get("NIJA_WRITER_GENERATION", "")
            or 0
        )
        lease_flag = str(os.environ.get("NIJA_WRITER_LEASE_ACQUIRED", "") or "").strip().lower()
        if expected <= 0 or lease_flag not in {"1", "true", "yes", "on", "enabled", "y"}:
            ok, generation, reason = repair_or_reacquire(f"v42:{source}")
            if not ok:
                LOGGER.warning(
                    "WRITER_V77_PRE_REANCHOR_BLOCKED marker=%s source=%s reason=%s generation=%s",
                    MARKER,
                    source,
                    reason,
                    generation,
                )
        return current(source)

    setattr(attempt_reanchor_v77, _PATCH_ATTR, True)
    setattr(attempt_reanchor_v77, "__wrapped__", current)
    module._attempt_reanchor = attempt_reanchor_v77
    LOGGER.critical("WRITER_V77_V42_PATCHED marker=%s module=%s", MARKER, module.__name__)
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in _V42_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_v42(module) or changed
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                module = original_import(name, globals, locals, fromlist, level)
                if "heartbeat_authority_reanchor_v42" in str(name):
                    _patch_loaded()
                return module

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)
        os.environ["NIJA_WRITER_AUTHORITY_RECONSTITUTION_V77_INSTALLED"] = "1"
        LOGGER.critical(
            "WRITER_AUTHORITY_RECONSTITUTION_V77_INSTALLED marker=%s exact_owner_only=true bounded_reacquire=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "exact_owner_proof",
    "publish_local_lineage",
    "repair_or_reacquire",
    "install",
    "install_import_hook",
]
