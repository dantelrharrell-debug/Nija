"""Prevent soft authority probe timeouts from forcing emergency stop.

The authority heartbeat can time out while the process still owns the Redis
writer lock and the local writer generation matches Redis.  In that case the
failure is a slow status probe, not lost writer authority.  This repair wraps the
lockdown trigger and grants a bounded grace only when the current process proves
it still owns the fencing token in Redis.

It does not grant writer authority, bypass generation mismatches, ignore Redis
outages, change risk sizing, or submit orders.
"""
from __future__ import annotations

import functools
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("nija.authority_heartbeat_timeout_grace")

_MARKER = "20260731-authority-heartbeat-timeout-grace-v1"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False
_ORIGINAL_TRIGGER = None


def _truthy_env(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _timeout_text(reason: str) -> bool:
    text = str(reason or "").lower()
    return "authority check timed out" in text and "redis ping timed out" not in text


def _int_string(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(int(str(value).strip()))


def _redis_client(redis_url: str, timeout_s: float) -> Any:
    import redis as redis_lib

    bounded_timeout = max(0.5, min(float(timeout_s or 1.0), 3.0))
    return redis_lib.from_url(
        redis_url,
        socket_connect_timeout=bounded_timeout,
        socket_timeout=bounded_timeout,
        decode_responses=False,
    )


def _redis_url() -> str:
    try:
        from bot.redis_env import get_redis_url
    except ImportError:
        from redis_env import get_redis_url  # type: ignore[import]

    return str(get_redis_url() or "").strip()


def _verified_current_writer(timeout_s: float) -> tuple[bool, str]:
    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    if not token:
        return False, "token_missing"

    local_generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
    if not local_generation:
        return False, "local_generation_missing"

    redis_url = _redis_url()
    if not redis_url:
        return False, "redis_url_missing"

    try:
        client = _redis_client(redis_url, timeout_s)

        generation_key = (
            os.environ.get("NIJA_LEASE_GENERATION_KEY", "").strip()
            or "nija:lease:generation"
        )
        redis_generation = client.get(generation_key)
        if redis_generation is None:
            return False, f"redis_generation_missing:{generation_key}"
        if _int_string(redis_generation) != _int_string(local_generation):
            return False, (
                "generation_mismatch:"
                f"local={local_generation}:redis={_int_string(redis_generation)}"
            )

        lock_scope = os.environ.get("NIJA_WRITER_SCOPE", "platform")
        lock_key = (
            os.environ.get("NIJA_WRITER_LOCK_KEY", "").strip()
            or f"nija:writer_lock:{lock_scope}"
        )
        lock_value = client.get(lock_key)
        if lock_value is None:
            return False, f"writer_lock_missing:{lock_key}"
        if isinstance(lock_value, bytes):
            lock_value = lock_value.decode("utf-8", errors="replace")
        lock_prefix = str(lock_value or "").split(":", 1)[0]
        if lock_prefix != token:
            return False, f"writer_lock_token_mismatch:{lock_prefix[:8]}"

        return True, f"generation={local_generation}:lock_key={lock_key}:token_prefix={token[:8]}"
    except Exception as exc:
        return False, f"verification_error:{type(exc).__name__}:{exc}"


def _refresh_healthy_heartbeat(module: Any, monitor: Any) -> None:
    now = str(time.time())
    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
    os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = now

    writer = getattr(module, "_write_heartbeat_marker", None)
    if callable(writer):
        try:
            writer()
        except Exception as exc:
            logger.warning(
                "AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_MARKER_REFRESH_FAILED marker=%s err=%s",
                _MARKER,
                exc,
            )

    redis_writer = getattr(monitor, "_write_heartbeat_to_redis", None)
    if callable(redis_writer):
        try:
            redis_writer()
        except Exception as exc:
            logger.warning(
                "AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_REDIS_REFRESH_FAILED marker=%s err=%s",
                _MARKER,
                exc,
            )


def install_import_hook() -> bool:
    """Install the heartbeat timeout grace wrapper."""
    global _INSTALLED, _ORIGINAL_TRIGGER

    with _LOCK:
        if _INSTALLED:
            return True

        try:
            try:
                from bot import authority_heartbeat as module
            except ImportError:
                import authority_heartbeat as module  # type: ignore[import]

            cls = getattr(module, "AuthorityHeartbeatMonitor", None)
            if cls is None:
                return False
            current_trigger = getattr(cls, "_trigger_lockdown", None)
            if not callable(current_trigger):
                return False
            if bool(getattr(current_trigger, "_nija_timeout_grace_patch", False)):
                _INSTALLED = True
                return True

            _ORIGINAL_TRIGGER = current_trigger

            @functools.wraps(current_trigger)
            def _trigger_lockdown_with_timeout_grace(self: Any, reason: str) -> None:
                reason_text = str(reason or "")
                if (
                    not _truthy_env("NIJA_AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_DISABLED")
                    and _timeout_text(reason_text)
                    and not getattr(self, "_last_failure_is_generation_mismatch", False)
                ):
                    timeout_s = float(getattr(self, "_timeout_s", 3.0) or 3.0)
                    verified, detail = _verified_current_writer(timeout_s)
                    if verified:
                        self._consecutive_failures = 0
                        self._last_failure_reason = ""
                        self._last_failure_is_generation_mismatch = False
                        _refresh_healthy_heartbeat(module, self)
                        logger.warning(
                            "AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_APPLIED marker=%s reason=%s detail=%s",
                            _MARKER,
                            reason_text,
                            detail,
                        )
                        return
                    logger.critical(
                        "AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_DENIED marker=%s reason=%s detail=%s",
                        _MARKER,
                        reason_text,
                        detail,
                    )

                return current_trigger(self, reason)

            setattr(_trigger_lockdown_with_timeout_grace, "_nija_timeout_grace_patch", True)
            cls._trigger_lockdown = _trigger_lockdown_with_timeout_grace
            os.environ["NIJA_AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_PATCH"] = "1"
            _INSTALLED = True
            logger.warning(
                "AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_INSTALLED marker=%s",
                _MARKER,
            )
            return True
        except Exception as exc:
            logger.warning(
                "AUTHORITY_HEARTBEAT_TIMEOUT_GRACE_INSTALL_FAILED marker=%s err=%s",
                _MARKER,
                exc,
                exc_info=True,
            )
            return False


def install() -> bool:
    return install_import_hook()


__all__ = ["install", "install_import_hook", "_verified_current_writer"]
