"""Keep authority heartbeat generation aligned with the platform Kraken lease.

The legacy heartbeat writer read the global ``nija:lease:generation`` counter.
Every user Kraken nonce lease increments that counter, so Daivon and Tania could
make the platform heartbeat appear stale even while the platform lease remained
healthy.  This repair reads the platform key's own lease version through the
already-scoped writer generation tracker and never copies the global counter
into platform writer lineage.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.authority_heartbeat_generation_scope")
MARKER = "20260713a"
_LOCK = threading.RLock()
_INSTALLED = False
_WATCHDOG_STARTED = False


def _platform_generation() -> tuple[int, str]:
    try:
        try:
            from bot.writer_generation_tracker import get_redis_generation
        except ImportError:
            from writer_generation_tracker import get_redis_generation  # type: ignore[import]
        generation, error = get_redis_generation()
        return max(0, int(generation or 0)), str(error or "")
    except Exception as exc:
        return 0, f"platform_generation_lookup_failed:{exc}"


def _redis_url() -> str:
    try:
        try:
            from bot.redis_env import get_redis_url
        except ImportError:
            from redis_env import get_redis_url  # type: ignore[import]
        return str(get_redis_url() or "").strip()
    except Exception:
        return ""


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "AuthorityHeartbeatMonitor", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_write_heartbeat_to_redis", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_platform_generation_scoped_20260713a", False):
        return True

    def _write_heartbeat_to_redis(self: Any) -> None:
        redis_url = _redis_url()
        if not redis_url:
            logger.debug("AUTHORITY_HEARTBEAT_PLATFORM_SCOPE_SKIP marker=%s reason=redis_not_configured", MARKER)
            return

        generation, generation_error = _platform_generation()
        if generation_error or generation <= 0:
            # Fail closed: do not publish a heartbeat with an unverified or global
            # generation.  The authority check remains responsible for lockdown.
            logger.error(
                "AUTHORITY_HEARTBEAT_PLATFORM_GENERATION_UNAVAILABLE marker=%s error=%s",
                MARKER,
                generation_error or "invalid_platform_generation",
            )
            return

        local_before = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
        if local_before != str(generation):
            logger.warning(
                "AUTHORITY_HEARTBEAT_PLATFORM_GENERATION_REPAIRED marker=%s local=%s platform=%s",
                MARKER,
                local_before or "unset",
                generation,
            )
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = str(generation)
        os.environ["NIJA_WRITER_LEASE_GENERATION_LAST"] = str(generation)

        try:
            import redis as redis_lib

            client = redis_lib.from_url(redis_url, socket_connect_timeout=3)
            self._redis_client = client
            heartbeat_data = {
                "timestamp": time.time(),
                "generation": str(generation),
                "generation_scope": "platform_kraken_key",
                "instance_id": os.environ.get("NIJA_WRITER_INSTANCE_ID", "unknown"),
            }
            client.set("nija:writer_heartbeat_active", json.dumps(heartbeat_data), ex=30)

            lock_scope = os.environ.get("NIJA_WRITER_SCOPE", "platform")
            lock_key = (
                os.environ.get("NIJA_WRITER_LOCK_KEY", "").strip()
                or f"nija:writer_lock:{lock_scope}"
            )
            lock_ttl_s = max(
                60,
                int(os.environ.get("NIJA_WRITER_LOCK_TTL_S", "30") or 30) * 3,
            )
            expected_token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
            if expected_token:
                current_lock = client.get(lock_key)
                if current_lock is not None:
                    if isinstance(current_lock, bytes):
                        current_lock = current_lock.decode("utf-8", errors="replace")
                    current_prefix = str(current_lock or "").split(":", 1)[0]
                    if current_prefix == expected_token:
                        client.expire(lock_key, lock_ttl_s)
                    else:
                        logger.critical(
                            "AUTHORITY_HEARTBEAT_LOCK_OWNER_MISMATCH marker=%s lock_key=%s expected=%s actual=%s",
                            MARKER,
                            lock_key,
                            expected_token[:8],
                            current_prefix[:8],
                        )
                else:
                    owner_id = os.environ.get("NIJA_WRITER_OWNER_ID", "heartbeat_recovered")
                    lock_value = f"{expected_token}:{owner_id}"
                    reacquired = client.set(lock_key, lock_value, ex=lock_ttl_s, nx=True)
                    if reacquired:
                        logger.warning(
                            "AUTHORITY_HEARTBEAT_LOCK_REACQUIRED marker=%s lock_key=%s token_prefix=%s",
                            MARKER,
                            lock_key,
                            expected_token[:8],
                        )
                    else:
                        logger.critical(
                            "AUTHORITY_HEARTBEAT_LOCK_REACQUIRE_FAILED marker=%s lock_key=%s token_prefix=%s",
                            MARKER,
                            lock_key,
                            expected_token[:8],
                        )

            logger.info(
                "AUTHORITY_HEARTBEAT_PLATFORM_GENERATION_PUBLISHED marker=%s generation=%s",
                MARKER,
                generation,
            )
        except Exception as exc:
            logger.error(
                "AUTHORITY_HEARTBEAT_PLATFORM_WRITE_FAILED marker=%s error=%s",
                MARKER,
                exc,
                exc_info=True,
            )

    _write_heartbeat_to_redis._nija_platform_generation_scoped_20260713a = True  # type: ignore[attr-defined]
    _write_heartbeat_to_redis.__wrapped__ = current  # type: ignore[attr-defined]
    setattr(cls, "_write_heartbeat_to_redis", _write_heartbeat_to_redis)
    logger.warning("AUTHORITY_HEARTBEAT_GENERATION_SCOPE_PATCHED marker=%s", MARKER)
    return True


def _try_loaded() -> bool:
    patched = False
    for name in ("bot.authority_heartbeat", "authority_heartbeat"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def _watchdog() -> None:
    deadline = time.monotonic() + max(
        60.0,
        float(os.environ.get("NIJA_AUTHORITY_HEARTBEAT_SCOPE_WATCHDOG_S", "600") or 600),
    )
    while time.monotonic() < deadline:
        try:
            if _try_loaded():
                # Continue briefly because some runtimes import the same module
                # under both package and top-level names.
                pass
        except Exception as exc:
            logger.debug("AUTHORITY_HEARTBEAT_SCOPE_RETRY marker=%s error=%s", MARKER, exc)
        time.sleep(0.25)


def install() -> bool:
    global _INSTALLED, _WATCHDOG_STARTED
    with _LOCK:
        _INSTALLED = _try_loaded() or _INSTALLED
        if not _WATCHDOG_STARTED:
            _WATCHDOG_STARTED = True
            threading.Thread(
                target=_watchdog,
                name="AuthorityHeartbeatGenerationScopeWatchdog",
                daemon=True,
            ).start()
        os.environ["NIJA_AUTHORITY_HEARTBEAT_GENERATION_SCOPE_INSTALLED"] = "1"
        logger.warning(
            "AUTHORITY_HEARTBEAT_GENERATION_SCOPE_REPAIR_INSTALLED marker=%s patched=%s",
            MARKER,
            _INSTALLED,
        )
        return True


def installed() -> bool:
    return _INSTALLED or _WATCHDOG_STARTED


__all__ = ["install", "installed", "_patch_module", "_platform_generation"]
