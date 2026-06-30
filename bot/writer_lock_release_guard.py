"""Process-exit writer lock release guard.

Railway can briefly run old and new deployments during rollout. The strict
Redis writer lock is correct, but handoff is slow if the old process keeps
renewing until the platform stops it. This module installs a small process-level
SIGTERM/SIGINT/atexit guard that releases Redis writer ownership only when the
current process still owns the exact lock value.

It does not acquire locks, bypass locks, submit orders, cancel orders, or delete
another instance's lock.
"""

from __future__ import annotations

import atexit
import hashlib
import logging
import os
import signal
import threading
import time
from typing import Any

logger = logging.getLogger("nija.writer_lock_release_guard")
_INSTALLED = False
_RELEASING = False
_LOCK = threading.Lock()
_PREVIOUS_HANDLERS: dict[int, Any] = {}


def _clean(value: str | None) -> str:
    return str(value or "").strip().strip('"').strip("'").strip()


def _resolve_scope() -> str:
    raw = _clean(os.getenv("NIJA_WRITER_LOCK_SCOPE"))
    if raw:
        return raw
    key = _clean(os.getenv("KRAKEN_PLATFORM_API_KEY")) or _clean(os.getenv("KRAKEN_API_KEY")) or "default"
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
        logger.warning("WRITER_LOCK_RELEASE_GUARD_REDIS_UNAVAILABLE error=%s", exc)
        return None


def _expected_owner_parts() -> list[str]:
    parts = []
    token = _clean(os.getenv("NIJA_WRITER_FENCING_TOKEN"))
    if token:
        parts.append(token)
    for key in ("RAILWAY_DEPLOYMENT_ID", "RAILWAY_REPLICA_ID", "RAILWAY_SERVICE_ID", "HOSTNAME"):
        value = _clean(os.getenv(key))
        if value:
            parts.append(value)
    return parts


def release_owned_writer_lock(reason: str = "process_exit") -> bool:
    global _RELEASING
    with _LOCK:
        if _RELEASING:
            return False
        _RELEASING = True
    try:
        client = _redis_client()
        if client is None:
            return False
        lock_key = _lock_key()
        meta_key = _meta_key()
        current = str(client.get(lock_key) or "")
        if not current:
            logger.warning("WRITER_LOCK_RELEASE_GUARD_NO_LOCK reason=%s key=%s", reason, lock_key)
            return False
        expected_parts = [p for p in _expected_owner_parts() if p]
        owns_lock = any(part in current for part in expected_parts)
        if not owns_lock:
            logger.warning(
                "WRITER_LOCK_RELEASE_GUARD_SKIP_NOT_OWNER reason=%s key=%s current_prefix=%s expected_parts=%d",
                reason,
                lock_key,
                current[:64],
                len(expected_parts),
            )
            return False
        payload = (
            "{"
            f"\"released_at\":{time.time()},"
            f"\"reason\":\"{reason}\","
            f"\"deployment\":\"{_clean(os.getenv('RAILWAY_DEPLOYMENT_ID'))}\""
            "}"
        )
        client.set(_release_key(lock_key), payload, px=120000)
        client.delete(lock_key)
        client.delete(meta_key)
        for env_key in ("NIJA_WRITER_FENCING_TOKEN", "NIJA_WRITER_LEASE_ACQUIRED", "NIJA_LOCK_ACQUIRED"):
            os.environ.pop(env_key, None)
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
        logger.critical("WRITER_LOCK_RELEASED_ON_EXIT reason=%s key=%s owner_prefix=%s", reason, lock_key, current[:64])
        return True
    except Exception as exc:
        logger.warning("WRITER_LOCK_RELEASE_GUARD_ERROR reason=%s error=%s", reason, exc)
        return False
    finally:
        with _LOCK:
            _RELEASING = False


def _signal_handler(signum: int, frame: Any) -> None:
    name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT" if signum == signal.SIGINT else str(signum)
    release_owned_writer_lock(f"signal:{name}")
    previous = _PREVIOUS_HANDLERS.get(signum)
    if callable(previous):
        try:
            previous(signum, frame)
            return
        except SystemExit:
            raise
        except Exception as exc:
            logger.warning("WRITER_LOCK_RELEASE_GUARD_PREVIOUS_HANDLER_ERROR signal=%s error=%s", name, exc)
    if previous == signal.SIG_DFL:
        raise SystemExit(0)


def install_import_hook() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    atexit.register(lambda: release_owned_writer_lock("atexit"))
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            _PREVIOUS_HANDLERS[sig] = signal.getsignal(sig)
            signal.signal(sig, _signal_handler)
        except Exception as exc:
            logger.warning("WRITER_LOCK_RELEASE_GUARD_SIGNAL_INSTALL_FAILED signal=%s error=%s", sig, exc)
    logger.warning("WRITER_LOCK_RELEASE_GUARD_INSTALLED")
