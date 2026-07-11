"""Process-exit writer lock release guard.

Zero-downtime deployments can briefly run old and new instances together. This
module shortens a legitimate handoff only when the *current Python process* can
prove that it owns the exact Redis lock value. Auxiliary Python processes,
Docker health checks, child processes, and replacement instances must never be
able to release another process's lease merely because they share a hostname or
service identity.

Before deleting an owned lease, this guard stops and joins the canonical writer
heartbeat. That ordering prevents the heartbeat's lost-key recovery branch from
recreating the lease immediately after deletion and leaving a countdown-only
lock behind during deployment handoff.

The guard does not acquire locks, bypass writer fencing, submit orders, cancel
orders, or delete a non-matching lease.
"""

from __future__ import annotations

import atexit
import builtins
import hashlib
import json
import logging
import os
import signal
import sys
import threading
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.writer_lock_release_guard")
_MARKER = "20260711e"
_INSTALLED = False
_RELEASING = False
_LOCK = threading.Lock()
_PREVIOUS_HANDLERS: dict[int, Any] = {}
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_PROCESS_INSTALL_MARKER = "_NIJA_WRITER_LOCK_RELEASE_GUARD_INSTALLED_20260711e"
_ENTRYPOINT_PATCH_ATTR = "_nija_writer_release_quiesce_v20260711e"
_ENTRYPOINT_PATCH_MONITOR_ATTR = "_NIJA_WRITER_RELEASE_PATCH_MONITOR_20260711e"


def _clean(value: str | None) -> str:
    return str(value or "").strip().strip('"').strip("'").strip()


def _truthy(name: str) -> bool:
    return _clean(os.getenv(name)).lower() in _TRUE


def _resolve_scope() -> str:
    raw = _clean(os.getenv("NIJA_WRITER_LOCK_SCOPE"))
    if raw:
        return raw
    key = (
        _clean(os.getenv("KRAKEN_PLATFORM_API_KEY"))
        or _clean(os.getenv("KRAKEN_API_KEY"))
        or "default"
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _lock_key() -> str:
    return _clean(os.getenv("NIJA_WRITER_LOCK_KEY")) or f"nija:writer_lock:{_resolve_scope()}"


def _meta_key() -> str:
    return _clean(os.getenv("NIJA_WRITER_LOCK_META_KEY")) or f"nija:writer_lock_meta:{_resolve_scope()}"


def _release_key(lock_key: str) -> str:
    return f"nija:writer_lock:released:{lock_key}"


def _redis_client():
    try:
        from bot.redis_env import get_redis_url
        from bot.redis_runtime import connect_redis_with_fallback
    except Exception:
        try:
            from redis_env import get_redis_url  # type: ignore
            from redis_runtime import connect_redis_with_fallback  # type: ignore
        except Exception:
            return None
    url = get_redis_url()
    if not url:
        return None
    try:
        client, _ = connect_redis_with_fallback(
            url=url,
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
            retries=1,
            delay_s=0.0,
            log=lambda msg: logger.debug("release guard redis: %s", msg),
        )
        return client
    except Exception as exc:
        logger.warning(
            "WRITER_LOCK_RELEASE_GUARD_REDIS_UNAVAILABLE marker=%s error=%s",
            _MARKER,
            exc,
        )
        return None


def _local_authority_proof() -> tuple[bool, str, str]:
    """Return an exact expected lock value only for this owning process."""

    token = _clean(os.getenv("NIJA_WRITER_FENCING_TOKEN"))
    owner = _clean(os.getenv("NIJA_WRITER_OWNER_ID"))
    generation = _clean(os.getenv("NIJA_WRITER_LEASE_GENERATION"))
    lease = _truthy("NIJA_WRITER_LEASE_ACQUIRED") and _truthy("NIJA_LOCK_ACQUIRED")

    if not token:
        return False, "", "fencing_token_missing"
    if not owner:
        return False, "", "owner_id_missing"
    if not generation:
        return False, "", "lease_generation_missing"
    if not lease:
        return False, "", "local_lease_flags_missing"

    pid_marker = f"pid={os.getpid()}"
    if pid_marker not in owner:
        return False, "", f"owner_pid_mismatch:{pid_marker}"

    return True, f"{token}:{owner}", "exact_local_authority"


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _entrypoint_modules() -> list[ModuleType]:
    modules: list[ModuleType] = []
    seen: set[int] = set()
    for name in ("bot.entrypoint_writer_authority", "entrypoint_writer_authority"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            modules.append(module)
    return modules


def _quiesce_runtime(runtime: Any, timeout_s: float = 2.0) -> tuple[bool, str]:
    """Stop and join the canonical Redis-renewal thread before lock deletion."""

    if runtime is None:
        return True, "runtime_absent"

    stop = getattr(runtime, "_stop", None)
    if stop is not None and callable(getattr(stop, "set", None)):
        stop.set()

    thread = getattr(runtime, "_heartbeat_thread", None)
    if isinstance(thread, threading.Thread) and thread is not threading.current_thread():
        if thread.is_alive():
            thread.join(timeout=max(0.1, float(timeout_s)))
        if thread.is_alive():
            return False, "heartbeat_thread_still_alive"
    return True, "heartbeat_quiesced"


def _quiesce_local_writer_runtime(timeout_s: float = 2.0) -> tuple[bool, str]:
    """Publish release intent and stop any loaded canonical writer runtime."""

    os.environ["NIJA_WRITER_RELEASE_IN_PROGRESS"] = "1"
    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
    os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"
    os.environ["NIJA_LOCK_ACQUIRED"] = "false"

    runtimes: list[Any] = []
    for module in _entrypoint_modules():
        runtime = getattr(module, "_SINGLETON", None)
        if runtime is not None and all(runtime is not item for item in runtimes):
            runtimes.append(runtime)

    for runtime in runtimes:
        ok, reason = _quiesce_runtime(runtime, timeout_s=timeout_s)
        if not ok:
            return False, reason
    return True, "all_writer_heartbeats_quiesced" if runtimes else "runtime_absent"


def _patch_entrypoint_authority_module(module: ModuleType) -> bool:
    """Make canonical release wait for its own heartbeat before compare-delete."""

    cls = getattr(module, "EntrypointWriterAuthority", None)
    if not isinstance(cls, type):
        return False
    if bool(getattr(cls, _ENTRYPOINT_PATCH_ATTR, False)):
        return True

    original_release = getattr(cls, "release", None)
    original_tick = getattr(cls, "_heartbeat_tick", None)
    if not callable(original_release) or not callable(original_tick):
        return False

    def guarded_tick(self: Any):
        stop = getattr(self, "_stop", None)
        if _truthy("NIJA_WRITER_RELEASE_IN_PROGRESS") or bool(
            stop is not None and callable(getattr(stop, "is_set", None)) and stop.is_set()
        ):
            return False, "release_in_progress"
        return original_tick(self)

    def guarded_release(self: Any) -> bool:
        os.environ["NIJA_WRITER_RELEASE_IN_PROGRESS"] = "1"
        ok, reason = _quiesce_runtime(self, timeout_s=2.0)
        if not ok:
            logger.error(
                "ENTRYPOINT_WRITER_RELEASE_DEFERRED marker=%s reason=%s "
                "lock_delete_skipped=true",
                _MARKER,
                reason,
            )
            return False
        return bool(original_release(self))

    setattr(guarded_tick, "__wrapped__", original_tick)
    setattr(guarded_release, "__wrapped__", original_release)
    setattr(cls, "_heartbeat_tick", guarded_tick)
    setattr(cls, "release", guarded_release)
    setattr(cls, _ENTRYPOINT_PATCH_ATTR, True)
    logger.warning(
        "ENTRYPOINT_WRITER_RELEASE_QUIESCE_PATCHED marker=%s module=%s",
        _MARKER,
        module.__name__,
    )
    return True


def _patch_entrypoint_authority_loaded() -> bool:
    patched = False
    for module in _entrypoint_modules():
        try:
            patched = _patch_entrypoint_authority_module(module) or patched
        except Exception as exc:
            logger.warning(
                "ENTRYPOINT_WRITER_RELEASE_QUIESCE_PATCH_FAILED marker=%s module=%s err=%s",
                _MARKER,
                module.__name__,
                exc,
            )
    return patched


def _entrypoint_patch_monitor() -> None:
    deadline = time.monotonic() + 300.0
    while time.monotonic() < deadline:
        if _patch_entrypoint_authority_loaded():
            return
        time.sleep(0.05)
    logger.warning(
        "ENTRYPOINT_WRITER_RELEASE_QUIESCE_PATCH_TIMEOUT marker=%s",
        _MARKER,
    )


def release_owned_writer_lock(reason: str = "process_exit") -> bool:
    """Stop local renewals, then compare-and-delete only this exact lease."""

    global _RELEASING
    with _LOCK:
        if _RELEASING:
            return False
        _RELEASING = True

    try:
        proven, expected_lock_value, proof_reason = _local_authority_proof()
        if not proven:
            logger.info(
                "WRITER_LOCK_RELEASE_GUARD_SKIP_NO_LOCAL_AUTHORITY marker=%s reason=%s proof=%s pid=%s",
                _MARKER,
                reason,
                proof_reason,
                os.getpid(),
            )
            return False

        quiesced, quiesce_reason = _quiesce_local_writer_runtime(timeout_s=2.0)
        if not quiesced:
            logger.error(
                "WRITER_LOCK_RELEASE_GUARD_SKIP_HEARTBEAT_ACTIVE marker=%s reason=%s "
                "quiesce=%s lock_delete_skipped=true",
                _MARKER,
                reason,
                quiesce_reason,
            )
            return False

        client = _redis_client()
        if client is None:
            return False

        lock_key = _lock_key()
        meta_key = _meta_key()
        release_key = _release_key(lock_key)
        payload = json.dumps(
            {
                "released_at": time.time(),
                "reason": reason,
                "pid": os.getpid(),
                "generation": _clean(os.getenv("NIJA_WRITER_LEASE_GENERATION")),
                "instance_id": _clean(os.getenv("NIJA_WRITER_INSTANCE_ID")),
                "source": "writer_lock_release_guard",
                "marker": _MARKER,
                "heartbeat_quiesced": True,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        script = """
        local current = redis.call('GET', KEYS[1])
        if not current then
            return {0, ''}
        end
        if current ~= ARGV[1] then
            return {0, current}
        end
        redis.call('SET', KEYS[3], ARGV[2], 'PX', tonumber(ARGV[3]))
        redis.call('DEL', KEYS[1])
        if KEYS[2] and KEYS[2] ~= '' then
            redis.call('DEL', KEYS[2])
        end
        return {1, current}
        """
        raw = client.eval(
            script,
            3,
            lock_key,
            meta_key,
            release_key,
            expected_lock_value,
            payload,
            "120000",
        )
        code = 0
        observed = ""
        if isinstance(raw, (list, tuple)):
            try:
                code = int(raw[0] or 0)
            except (TypeError, ValueError, IndexError):
                code = 0
            if len(raw) > 1:
                observed = _as_text(raw[1])
        else:
            try:
                code = int(raw or 0)
            except (TypeError, ValueError):
                code = 0

        if code != 1:
            logger.warning(
                "WRITER_LOCK_RELEASE_GUARD_SKIP_NOT_EXACT_OWNER marker=%s reason=%s key=%s "
                "expected_prefix=%s observed_prefix=%s",
                _MARKER,
                reason,
                lock_key,
                expected_lock_value[:64],
                observed[:64],
            )
            return False

        for env_key in (
            "NIJA_WRITER_FENCING_TOKEN",
            "NIJA_WRITER_OWNER_ID",
            "NIJA_WRITER_INSTANCE_ID",
            "NIJA_WRITER_LEASE_GENERATION",
            "NIJA_WRITER_LEASE_ACQUIRED",
            "NIJA_LOCK_ACQUIRED",
        ):
            os.environ.pop(env_key, None)
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
        logger.critical(
            "WRITER_LOCK_RELEASED_ON_EXIT marker=%s reason=%s key=%s owner_prefix=%s "
            "heartbeat_quiesced=true",
            _MARKER,
            reason,
            lock_key,
            expected_lock_value[:64],
        )
        return True
    except Exception as exc:
        logger.warning(
            "WRITER_LOCK_RELEASE_GUARD_ERROR marker=%s reason=%s error=%s",
            _MARKER,
            reason,
            exc,
        )
        return False
    finally:
        with _LOCK:
            _RELEASING = False


def _signal_handler(signum: int, frame: Any) -> None:
    name = (
        "SIGTERM"
        if signum == signal.SIGTERM
        else "SIGINT"
        if signum == signal.SIGINT
        else str(signum)
    )
    release_owned_writer_lock(f"signal:{name}")
    previous = _PREVIOUS_HANDLERS.get(signum)
    if callable(previous):
        try:
            previous(signum, frame)
            return
        except SystemExit:
            raise
        except Exception as exc:
            logger.warning(
                "WRITER_LOCK_RELEASE_GUARD_PREVIOUS_HANDLER_ERROR marker=%s signal=%s error=%s",
                _MARKER,
                name,
                exc,
            )
    if previous == signal.SIG_DFL:
        raise SystemExit(0)


def install_import_hook() -> None:
    global _INSTALLED
    if _INSTALLED or bool(getattr(builtins, _PROCESS_INSTALL_MARKER, False)):
        _patch_entrypoint_authority_loaded()
        return
    with _LOCK:
        if _INSTALLED or bool(getattr(builtins, _PROCESS_INSTALL_MARKER, False)):
            _patch_entrypoint_authority_loaded()
            return
        _INSTALLED = True
        setattr(builtins, _PROCESS_INSTALL_MARKER, True)

    _patch_entrypoint_authority_loaded()
    if not bool(getattr(builtins, _ENTRYPOINT_PATCH_MONITOR_ATTR, False)):
        setattr(builtins, _ENTRYPOINT_PATCH_MONITOR_ATTR, True)
        thread = threading.Thread(
            target=_entrypoint_patch_monitor,
            name="writer-release-quiesce-patch-monitor",
            daemon=True,
        )
        thread.start()

    atexit.register(lambda: release_owned_writer_lock("atexit"))
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            _PREVIOUS_HANDLERS[sig] = signal.getsignal(sig)
            signal.signal(sig, _signal_handler)
        except Exception as exc:
            logger.warning(
                "WRITER_LOCK_RELEASE_GUARD_SIGNAL_INSTALL_FAILED marker=%s signal=%s error=%s",
                _MARKER,
                sig,
                exc,
            )
    logger.warning(
        "WRITER_LOCK_RELEASE_GUARD_INSTALLED marker=%s exact_owner_required=true "
        "heartbeat_quiesce_required=true",
        _MARKER,
    )
