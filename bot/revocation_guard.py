"""
NIJA Runtime Revocation Guard
==============================

Implements a pre-trade revocation check that runs before every order execution.
If the fencing token is revoked or expired, all order placement is immediately
blocked and a RuntimeError is raised.

Revocation state is stored in Redis with immediate propagation so that any
operator or automated system can revoke live trading authority in real time
across all running instances.

Redis Keys
----------
nija:revocation:active          — "1" when revocation is active, "0" or absent otherwise
nija:revocation:reason          — Human-readable revocation reason (optional)
nija:revocation:token           — The fencing token that was revoked (for targeted revocation)
nija:revocation:timestamp       — ISO-8601 timestamp of revocation

Usage
-----
    from bot.revocation_guard import check_revocation_or_raise

    # Call before every order placement:
    check_revocation_or_raise()

    # To revoke from an operator script or automated system:
    from bot.revocation_guard import revoke_live_execution
    revoke_live_execution(reason="Manual operator revocation")

Author: NIJA Trading Systems
Version: 1.0
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("nija.revocation_guard")

# ---------------------------------------------------------------------------
# Redis key constants
# ---------------------------------------------------------------------------

_KEY_ACTIVE = "nija:revocation:active"
_KEY_REASON = "nija:revocation:reason"
_KEY_TOKEN = "nija:revocation:token"
_KEY_TIMESTAMP = "nija:revocation:timestamp"

# TTL for revocation state in Redis (24 hours — long enough to survive restarts)
_REVOCATION_TTL_S: int = 86_400

# Cache TTL for local revocation status (avoid Redis round-trip on every order)
_LOCAL_CACHE_TTL_S: float = 2.0

# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cache_revoked: bool = False
_cache_reason: str = ""
_cache_last_check_ts: float = 0.0


def _get_redis_client():
    """Return a Redis client for revocation checks (never raises)."""
    try:
        try:
            from bot.redis_env import get_redis_url
            from bot.redis_runtime import create_redis
        except ImportError:
            from redis_env import get_redis_url  # type: ignore[import]
            from redis_runtime import create_redis  # type: ignore[import]

        redis_url = get_redis_url()
        if not redis_url:
            return None
        return create_redis(redis_url, decode_responses=True, socket_timeout=3, socket_connect_timeout=3)
    except Exception as exc:
        logger.warning("RevocationGuard: could not build Redis client: %s", exc)
        return None


def _fetch_revocation_status_from_redis() -> tuple[bool, str]:
    """Query Redis for current revocation status.

    Returns (is_revoked, reason).  On Redis failure, returns (True, error)
    to fail closed — if we cannot verify revocation status, we block trading.
    """
    client = _get_redis_client()
    if client is None:
        return True, (
            "LIVE EXECUTION REVOKED: Redis is unreachable — cannot verify "
            "revocation status. Trading blocked until Redis connectivity is restored."
        )

    try:
        active = client.get(_KEY_ACTIVE)
        if active == "1":
            reason = str(client.get(_KEY_REASON) or "Revocation active (no reason stored)")
            token = str(client.get(_KEY_TOKEN) or "")
            ts = str(client.get(_KEY_TIMESTAMP) or "")

            # If a specific token was revoked, check if it matches ours.
            our_token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
            if token and our_token and token != our_token:
                # Revocation targets a different token — not applicable to us.
                return False, ""

            return True, f"LIVE EXECUTION REVOKED: {reason} (revoked_at={ts})"
        return False, ""
    except Exception as exc:
        return True, (
            f"LIVE EXECUTION REVOKED: Redis revocation check failed ({exc}). "
            "Trading blocked until revocation status can be verified."
        )


def _refresh_cache() -> tuple[bool, str]:
    """Refresh the local revocation cache from Redis."""
    global _cache_revoked, _cache_reason, _cache_last_check_ts

    is_revoked, reason = _fetch_revocation_status_from_redis()
    with _cache_lock:
        _cache_revoked = is_revoked
        _cache_reason = reason
        _cache_last_check_ts = time.monotonic()
    return is_revoked, reason


def check_revocation_or_raise() -> None:
    """Check revocation status and raise RuntimeError if revoked.

    This function MUST be called before every order placement.  It uses a
    short-lived local cache to avoid a Redis round-trip on every single order
    while still propagating revocations within _LOCAL_CACHE_TTL_S seconds.

    Raises
    ------
    RuntimeError
        When revocation is active or Redis is unreachable.
    """
    global _cache_revoked, _cache_reason, _cache_last_check_ts

    now = time.monotonic()
    with _cache_lock:
        cache_age = now - _cache_last_check_ts
        if cache_age <= _LOCAL_CACHE_TTL_S:
            if _cache_revoked:
                reason = _cache_reason
                logger.critical("🚫 %s", reason)
                raise RuntimeError(reason)
            return

    # Cache expired — refresh from Redis.
    is_revoked, reason = _refresh_cache()
    if is_revoked:
        logger.critical("🚫 %s", reason)
        raise RuntimeError(reason)


def is_revoked() -> bool:
    """Return True when live execution is currently revoked.

    Non-raising convenience wrapper around check_revocation_or_raise().
    """
    try:
        check_revocation_or_raise()
        return False
    except RuntimeError:
        return True


def revoke_live_execution(
    reason: str = "Operator revocation",
    token: Optional[str] = None,
) -> bool:
    """Revoke live execution authority in Redis.

    Sets the revocation flag in Redis so all running instances will block
    order placement within _LOCAL_CACHE_TTL_S seconds.

    Parameters
    ----------
    reason:
        Human-readable reason for revocation (stored in Redis).
    token:
        Optional fencing token to target.  If provided, only instances
        holding this specific token are revoked.  If None, all instances
        are revoked.

    Returns
    -------
    bool
        True if revocation was successfully written to Redis.
    """
    client = _get_redis_client()
    if client is None:
        logger.critical(
            "RevocationGuard: cannot revoke — Redis is unreachable. "
            "Manual intervention required."
        )
        return False

    try:
        ts = datetime.now(timezone.utc).isoformat()
        pipe = client.pipeline()
        pipe.set(_KEY_ACTIVE, "1", ex=_REVOCATION_TTL_S)
        pipe.set(_KEY_REASON, reason, ex=_REVOCATION_TTL_S)
        pipe.set(_KEY_TIMESTAMP, ts, ex=_REVOCATION_TTL_S)
        if token:
            pipe.set(_KEY_TOKEN, token, ex=_REVOCATION_TTL_S)
        else:
            pipe.delete(_KEY_TOKEN)
        pipe.execute()

        # Immediately invalidate local cache.
        with _cache_lock:
            global _cache_revoked, _cache_reason, _cache_last_check_ts
            _cache_revoked = True
            _cache_reason = f"LIVE EXECUTION REVOKED: {reason} (revoked_at={ts})"
            _cache_last_check_ts = time.monotonic()

        logger.critical(
            "🚨 LIVE EXECUTION REVOKED: reason=%s token=%s ts=%s",
            reason,
            token or "<all>",
            ts,
        )
        return True
    except Exception as exc:
        logger.critical("RevocationGuard: failed to write revocation to Redis: %s", exc)
        return False


def clear_revocation() -> bool:
    """Clear the revocation flag in Redis (re-enable live execution).

    Should only be called after the underlying issue has been resolved and
    the operator has confirmed it is safe to resume trading.

    Returns
    -------
    bool
        True if revocation was successfully cleared in Redis.
    """
    client = _get_redis_client()
    if client is None:
        logger.critical(
            "RevocationGuard: cannot clear revocation — Redis is unreachable."
        )
        return False

    try:
        pipe = client.pipeline()
        pipe.set(_KEY_ACTIVE, "0", ex=_REVOCATION_TTL_S)
        pipe.delete(_KEY_REASON)
        pipe.delete(_KEY_TOKEN)
        pipe.delete(_KEY_TIMESTAMP)
        pipe.execute()

        with _cache_lock:
            global _cache_revoked, _cache_reason, _cache_last_check_ts
            _cache_revoked = False
            _cache_reason = ""
            _cache_last_check_ts = time.monotonic()

        logger.info("RevocationGuard: revocation cleared — live execution re-enabled")
        return True
    except Exception as exc:
        logger.critical("RevocationGuard: failed to clear revocation in Redis: %s", exc)
        return False


def get_revocation_status() -> dict:
    """Return current revocation status for diagnostics (never raises)."""
    try:
        client = _get_redis_client()
        if client is None:
            return {
                "redis_reachable": False,
                "revoked": True,
                "reason": "Redis unreachable",
                "token": "",
                "timestamp": "",
            }
        active = client.get(_KEY_ACTIVE)
        reason = str(client.get(_KEY_REASON) or "")
        token = str(client.get(_KEY_TOKEN) or "")
        ts = str(client.get(_KEY_TIMESTAMP) or "")
        return {
            "redis_reachable": True,
            "revoked": active == "1",
            "reason": reason,
            "token": token,
            "timestamp": ts,
        }
    except Exception as exc:
        return {
            "redis_reachable": False,
            "revoked": True,
            "reason": str(exc),
            "token": "",
            "timestamp": "",
        }


__all__ = [
    "check_revocation_or_raise",
    "is_revoked",
    "revoke_live_execution",
    "clear_revocation",
    "get_revocation_status",
]
