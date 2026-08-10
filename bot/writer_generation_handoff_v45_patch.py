"""NIJA writer-generation handoff convergence v45.

Production after v44 exposed a remaining generation-domain split:
EntrypointWriterAuthority and canonical HeartbeatState were on process-writer
generation 3337 while the mutable process environment had been overwritten to
10.  v42 correctly refused to regress the newer canonical heartbeat state, but
readers that still consume NIJA_WRITER_LEASE_GENERATION temporarily failed
closed until the entrypoint heartbeat republished its lineage.

v45 makes process-writer generation repair proof-driven and prevents Kraken
nonce leases from mutating process-writer lineage.

Safety contract:
* only EntrypointWriterAuthority can source process-writer generation;
* repair requires exact Redis lock value, fencing token, positive TTL, and the
  Redis process-generation key to match the runtime generation;
* nonce lease publication never writes process-writer generation/token fields;
* tracker sync/reacquisition helpers never use DistributedNonceManager as a
  process-writer lock recovery mechanism;
* missing/mismatched Redis proof stays fail-closed;
* no SEAK, kill-switch, emergency-stop, readiness, broker, or risk gate is
  cleared or bypassed.
"""
from __future__ import annotations

import builtins
import importlib
import json
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Optional

LOGGER = logging.getLogger("nija.writer_generation_handoff_v45")
MARKER = "20260807-writer-generation-handoff-v45"

_LOCK = threading.RLock()
_INSTALLED = False
_WATCHDOG_STARTED = False
_HOOK_FLAG = "_NIJA_WRITER_GENERATION_HANDOFF_V45_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_WRITER_GENERATION_HANDOFF_V45_IMPORTLIB_HOOK"

_TRACKER_PATCH = "_nija_writer_generation_handoff_v45_tracker"
_NONCE_PATCH = "_nija_writer_generation_handoff_v45_nonce"
_HEARTBEAT_PATCH = "_nija_writer_generation_handoff_v45_heartbeat"
_SCOPE_PATCH = "_nija_writer_generation_handoff_v45_scope"
_V42_PATCH = "_nija_writer_generation_handoff_v45_v42"

_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_PROCESS_GENERATION_KEY_DEFAULT = "nija:lease:generation"

_ENTRYPOINT_NAMES = ("bot.entrypoint_writer_authority", "entrypoint_writer_authority")
_TRACKER_NAMES = ("bot.writer_generation_tracker", "writer_generation_tracker")
_NONCE_NAMES = ("bot.distributed_nonce_manager", "distributed_nonce_manager")
_HEARTBEAT_NAMES = ("bot.authority_heartbeat", "authority_heartbeat")
_SCOPE_NAMES = ("authority_heartbeat_generation_scope_patch",)
_V42_NAMES = (
    "nija_heartbeat_authority_reanchor_v42_prebot",
    "bot.heartbeat_authority_reanchor_v42_patch",
    "heartbeat_authority_reanchor_v42_patch",
)


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


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


def _process_generation_key() -> str:
    return (
        str(os.environ.get("NIJA_LEASE_GENERATION_KEY", "") or "").strip()
        or _PROCESS_GENERATION_KEY_DEFAULT
    )


def _prove_process_writer() -> tuple[Optional[dict[str, Any]], str]:
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
        return None, "runtime_token_missing"
    if not lock_key or not lock_value:
        return None, "runtime_lock_identity_missing"
    if client is None:
        return None, "runtime_redis_client_missing"

    env_token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    if env_token != token:
        return None, "env_fencing_token_mismatch"

    try:
        current_lock = _text(client.get(lock_key))
    except Exception as exc:
        return None, f"redis_lock_read_error:{type(exc).__name__}:{exc}"
    if current_lock != lock_value:
        return None, "redis_lock_owner_mismatch" if current_lock else "redis_lock_missing"

    try:
        pttl_ms = _integer(client.pttl(lock_key), default=-2)
    except Exception as exc:
        return None, f"redis_lock_ttl_error:{type(exc).__name__}:{exc}"
    if pttl_ms <= 0:
        return None, f"redis_lock_ttl_not_positive:{pttl_ms}"

    generation_key = _process_generation_key()
    try:
        redis_generation = _integer(client.get(generation_key))
    except Exception as exc:
        return None, f"redis_generation_read_error:{type(exc).__name__}:{exc}"
    if redis_generation != generation:
        return None, (
            f"redis_generation_mismatch:runtime={generation}:redis={redis_generation}"
        )

    return {
        "runtime": runtime,
        "client": client,
        "generation": generation,
        "token": token,
        "lock_key": lock_key,
        "lock_value": lock_value,
        "pttl_ms": pttl_ms,
        "generation_key": generation_key,
    }, ""


def repair_process_generation(source: str = "v45") -> tuple[bool, int, str]:
    proof, reason = _prove_process_writer()
    if proof is None:
        return False, 0, reason
    generation = int(proof["generation"])
    before = {
        "lease": str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or ""),
        "alias": str(os.environ.get("NIJA_WRITER_GENERATION", "") or ""),
        "last": str(os.environ.get("NIJA_WRITER_LEASE_GENERATION_LAST", "") or ""),
        "expected": str(os.environ.get("NIJA_WRITER_LEASE_GENERATION_EXPECTED", "") or ""),
    }
    value = str(generation)
    os.environ["NIJA_WRITER_LEASE_GENERATION"] = value
    os.environ["NIJA_WRITER_GENERATION"] = value
    os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = value
    if before["expected"]:
        os.environ["NIJA_WRITER_LEASE_GENERATION_EXPECTED"] = value
    changed = any(
        item and item != value for item in (before["lease"], before["alias"], before["last"])
    ) or not before["lease"] or not before["alias"]
    if changed:
        LOGGER.critical(
            "WRITER_GENERATION_V45_REPAIRED marker=%s source=%s before=%s after=%s token_prefix=%s pttl_ms=%s",
            MARKER,
            source,
            before,
            value,
            str(proof["token"])[:8],
            proof["pttl_ms"],
        )
    return True, generation, "proof_verified"


def _advance_bootstrap_after_process_writer() -> None:
    proof, _ = _prove_process_writer()
    if proof is None:
        return
    for module_name in ("bot.bootstrap_state_machine", "bootstrap_state_machine"):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        getter = getattr(module, "get_bootstrap_fsm", None)
        enum = getattr(module, "BootstrapState", None)
        if not callable(getter):
            continue
        try:
            fsm = getter()
            current = getattr(getattr(fsm, "state", None), "value", getattr(fsm, "current_state", None))
            current = getattr(current, "value", current)
            if str(current) != "BOOT_INIT":
                return
            target = getattr(enum, "LOCK_ACQUIRED", "LOCK_ACQUIRED") if enum is not None else "LOCK_ACQUIRED"
            transition = getattr(fsm, "transition", None)
            if callable(transition):
                try:
                    transition(target, reason="process_writer_proof_after_nonce_lease")
                except TypeError:
                    transition(target, "process_writer_proof_after_nonce_lease")
            return
        except Exception:
            return


def _patch_nonce_module(module: ModuleType) -> bool:
    backend = getattr(module, "_PerKeyRedisBackend", None)
    if not isinstance(backend, type):
        return False
    current = getattr(backend, "_publish_lock_acquired_state", None)
    if getattr(current, _NONCE_PATCH, False):
        return True

    def publish_nonce_only(self: Any, lease_version: int) -> None:
        version = max(0, _integer(lease_version))
        os.environ["NIJA_NONCE_LEASE_ACQUIRED"] = "1"
        os.environ["NIJA_NONCE_LEASE_GENERATION"] = str(version)
        _advance_bootstrap_after_process_writer()
        ok, generation, reason = repair_process_generation("nonce_lease_publish")
        if not ok and _truthy("NIJA_WRITER_LEASE_ACQUIRED"):
            LOGGER.warning(
                "WRITER_GENERATION_V45_NONCE_PUBLISH_FAIL_CLOSED marker=%s nonce_generation=%s reason=%s",
                MARKER,
                version,
                reason,
            )
        elif ok:
            LOGGER.debug(
                "WRITER_GENERATION_V45_NONCE_SCOPED marker=%s nonce_generation=%s process_generation=%s",
                MARKER,
                version,
                generation,
            )

    setattr(publish_nonce_only, _NONCE_PATCH, True)
    setattr(publish_nonce_only, "_nija_nonce_generation_domain_v2", True)
    if callable(current):
        setattr(publish_nonce_only, "__wrapped__", current)
    backend._publish_lock_acquired_state = publish_nonce_only
    LOGGER.critical(
        "WRITER_GENERATION_V45_NONCE_PATCHED marker=%s module=%s process_env_mutation=false",
        MARKER,
        module.__name__,
    )
    return True


def _patch_tracker_module(module: ModuleType) -> bool:
    current_local = getattr(module, "get_local_generation", None)
    if not callable(current_local):
        return False
    if getattr(current_local, _TRACKER_PATCH, False):
        return True

    original_local = current_local

    @wraps(original_local)
    def get_local_generation() -> int:
        ok, generation, _ = repair_process_generation("tracker.get_local_generation")
        if ok:
            return generation
        return int(original_local())

    def reset_generation_to_redis() -> tuple[bool, str]:
        ok, generation, reason = repair_process_generation("tracker.reset_generation_to_redis")
        if ok:
            return True, f"generation_repaired_from_entrypoint_proof generation={generation}"
        return False, f"generation_repair_blocked:{reason}"

    def attempt_generation_sync_recovery(local: int, redis_gen: int) -> tuple[bool, str]:
        ok, generation, reason = repair_process_generation("tracker.sync_recovery")
        if ok:
            return True, (
                f"generation_repaired_from_entrypoint_proof local={local} "
                f"observed_redis={redis_gen} canonical={generation}"
            )
        return False, f"generation_sync_blocked:{reason}"

    def attempt_lock_reacquisition(timeout_s: float = 10.0) -> tuple[bool, int, str]:
        del timeout_s
        ok, generation, reason = repair_process_generation("tracker.reacquisition")
        if ok:
            return True, generation, "canonical_process_writer_already_proven"
        return False, 0, f"entrypoint_process_writer_recovery_required:{reason}"

    for fn in (
        get_local_generation,
        reset_generation_to_redis,
        attempt_generation_sync_recovery,
        attempt_lock_reacquisition,
    ):
        setattr(fn, _TRACKER_PATCH, True)
    module.get_local_generation = get_local_generation
    module.reset_generation_to_redis = reset_generation_to_redis
    module.attempt_generation_sync_recovery = attempt_generation_sync_recovery
    module.attempt_lock_reacquisition = attempt_lock_reacquisition
    LOGGER.critical(
        "WRITER_GENERATION_V45_TRACKER_PATCHED marker=%s module=%s nonce_reacquisition=false",
        MARKER,
        module.__name__,
    )
    return True


def _safe_heartbeat_writer(self: Any) -> None:
    proof, reason = _prove_process_writer()
    if proof is None:
        LOGGER.error(
            "WRITER_GENERATION_V45_HEARTBEAT_BLOCKED marker=%s reason=%s",
            MARKER,
            reason,
        )
        return
    repair_process_generation("authority_heartbeat")
    client = proof["client"]
    lock_key = str(proof["lock_key"])
    lock_value = str(proof["lock_value"])
    generation = int(proof["generation"])
    try:
        current_lock = _text(client.get(lock_key))
        if current_lock != lock_value:
            LOGGER.critical(
                "WRITER_GENERATION_V45_HEARTBEAT_OWNER_CHANGED marker=%s lock_key=%s action=skip",
                MARKER,
                lock_key,
            )
            return
        heartbeat_data = {
            "timestamp": time.time(),
            "generation": str(generation),
            "generation_scope": "entrypoint_process_writer",
            "instance_id": os.environ.get("NIJA_WRITER_INSTANCE_ID", "unknown"),
        }
        client.set("nija:writer_heartbeat_active", json.dumps(heartbeat_data), ex=30)
        LOGGER.info(
            "WRITER_GENERATION_V45_HEARTBEAT_PUBLISHED marker=%s generation=%s "
            "token_prefix=%s lock_mutation=false",
            MARKER,
            generation,
            str(proof["token"])[:8],
        )
    except Exception as exc:
        LOGGER.error(
            "WRITER_GENERATION_V45_HEARTBEAT_WRITE_FAILED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )


setattr(_safe_heartbeat_writer, _HEARTBEAT_PATCH, True)


def _patch_heartbeat_module(module: ModuleType) -> bool:
    cls = getattr(module, "AuthorityHeartbeatMonitor", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_write_heartbeat_to_redis", None)
    if getattr(current, _HEARTBEAT_PATCH, False):
        return True
    safe = _safe_heartbeat_writer
    if callable(current):
        try:
            setattr(safe, "__wrapped__", current)
        except Exception:
            pass
    cls._write_heartbeat_to_redis = safe
    LOGGER.critical(
        "WRITER_GENERATION_V45_HEARTBEAT_PATCHED marker=%s module=%s lock_recreate=false",
        MARKER,
        module.__name__,
    )
    return True


def _patch_scope_module(module: ModuleType) -> bool:
    def process_generation() -> tuple[int, str]:
        proof, reason = _prove_process_writer()
        if proof is None:
            return 0, reason
        return int(proof["generation"]), ""

    setattr(process_generation, _SCOPE_PATCH, True)
    module._platform_generation = process_generation

    current = getattr(module, "_patch_module", None)
    if callable(current) and not getattr(current, _SCOPE_PATCH, False):
        @wraps(current)
        def patch_module(target: ModuleType) -> bool:
            result = bool(current(target))
            _patch_heartbeat_module(target)
            return result

        setattr(patch_module, _SCOPE_PATCH, True)
        module._patch_module = patch_module
    LOGGER.critical(
        "WRITER_GENERATION_V45_SCOPE_PATCHED marker=%s module=%s source=entrypoint_process_writer",
        MARKER,
        module.__name__,
    )
    return True


def _patch_v42_module(module: ModuleType) -> bool:
    current = getattr(module, "_expected_generation", None)
    if not callable(current):
        return False
    if getattr(current, _V42_PATCH, False):
        return True

    @wraps(current)
    def expected_generation() -> int:
        proof, _ = _prove_process_writer()
        if proof is not None:
            generation = int(proof["generation"])
            repair_process_generation("v42.expected_generation")
            return generation
        return _integer(current())

    setattr(expected_generation, _V42_PATCH, True)
    module._expected_generation = expected_generation
    LOGGER.critical(
        "WRITER_GENERATION_V45_V42_PATCHED marker=%s module=%s",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for names, patcher in (
        (_NONCE_NAMES, _patch_nonce_module),
        (_TRACKER_NAMES, _patch_tracker_module),
        (_HEARTBEAT_NAMES, _patch_heartbeat_module),
        (_SCOPE_NAMES, _patch_scope_module),
        (_V42_NAMES, _patch_v42_module),
    ):
        for name in names:
            module = sys.modules.get(name)
            if isinstance(module, ModuleType) and id(module) not in seen:
                seen.add(id(module))
                try:
                    changed = patcher(module) or changed
                except Exception as exc:
                    LOGGER.debug(
                        "WRITER_GENERATION_V45_PATCH_DEFERRED marker=%s module=%s error=%s",
                        MARKER,
                        name,
                        exc,
                    )
    return changed


def _interesting(name: str) -> bool:
    text = str(name or "")
    return any(
        fragment in text
        for fragment in (
            "distributed_nonce_manager",
            "writer_generation_tracker",
            "authority_heartbeat",
            "authority_heartbeat_generation_scope_patch",
            "heartbeat_authority_reanchor_v42_patch",
            "entrypoint_writer_authority",
        )
    )


def _watchdog() -> None:
    started = time.monotonic()
    deadline = started + 900.0
    while time.monotonic() < deadline:
        try:
            _patch_loaded()
            repair_process_generation("watchdog")
        except Exception:
            pass
        elapsed = time.monotonic() - started
        time.sleep(0.25 if elapsed < 30.0 else 2.0)


def install_import_hook() -> bool:
    global _INSTALLED, _WATCHDOG_STARTED
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if _interesting(name):
                    _patch_loaded()
                    repair_process_generation(f"import:{name}")
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
                    repair_process_generation(f"importlib:{name}")
                return result

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        if not _WATCHDOG_STARTED:
            _WATCHDOG_STARTED = True
            threading.Thread(
                target=_watchdog,
                name="WriterGenerationHandoffV45",
                daemon=True,
            ).start()
        _INSTALLED = True
        os.environ["NIJA_WRITER_GENERATION_HANDOFF_V45_INSTALLED"] = "1"
        LOGGER.critical(
            "WRITER_GENERATION_HANDOFF_V45_INSTALLED marker=%s proof_required=true nonce_process_mutation=false tracker_nonce_reacquisition=false",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "repair_process_generation",
    "_prove_process_writer",
    "_patch_nonce_module",
    "_patch_tracker_module",
    "_patch_heartbeat_module",
    "_patch_scope_module",
    "_patch_v42_module",
]
