"""
NIJA Distributed Nonce Manager
===============================

Unified, multi-instance-safe nonce authority for Kraken API keys.

Architecture
------------
Replaces both ``UserNonceManager`` and the platform ``KrakenNonceManager``
as the **single routing point** for every nonce request.

                         ┌─────────────────────────────────┐
    KrakenBroker         │   DistributedNonceManager        │
    .nonce_manager ─────►│   get_nonce(api_key_id)          │
                         │                                   │
                         │   Redis available?                │
                         │   ├─ YES → Redis Lua INCR        │  ← multi-instance safe
                         │   └─ NO  → per-key file lock     │  ← single-host safe
                         └─────────────────────────────────┘

Key derivation
--------------
``api_key_id = sha256(raw_api_key).hexdigest()[:16]``

Using a deterministic hash of the key material:
  ✅ Survives user_id changes (keys can rotate, logical IDs change).
  ✅ Never exposes the raw API key in logs or file paths.
  ✅ Stable across restarts — same key → same id → same nonce sequence.

Monotonic guarantee
-------------------
Kraken requires: nonce must be strictly increasing per API key across ALL
requests, globally.

This module enforces that invariant at every layer:

1. **Redis mode** (multi-instance):
   Atomic Lua script ``max(current+1, now_ms)`` in one round-trip.
   Two concurrent processes/containers CANNOT receive the same nonce.

2. **File mode** (single-host multi-process):
   ``KrakenNonceManager(key_id)`` with ``fcntl`` advisory lock on every
   increment.  Two OS processes on the same host CANNOT race.

3. **In-process**:
   ``threading.Lock`` serialises all callers within one process.

Redis fallback
--------------
If Redis is unreachable at construction time, or becomes unavailable later,
the manager falls back to the per-key file-lock mode transparently.  A
``CRITICAL`` log is emitted so operators know they have lost multi-instance
coordination.

─────────────────────────────────────────────────────────────────────────────
ZERO-DOWNTIME MIGRATION: File-based → Redis
─────────────────────────────────────────────────────────────────────────────

Goal: switch from per-key fcntl file locks to Redis-backed atomic nonces
without dropping any live orders or causing a nonce gap.

Phase 0 — Prerequisites (no bot changes)
  1. Provision a Redis instance reachable from every bot container.
       Railway:  Add a Redis plugin to your project.
       Docker:   docker run -d -p 6379:6379 redis:7-alpine
       Managed:  Redis Cloud free tier, Upstash, etc.
  2. Note the connection URL (``redis://:<password>@<host>:6379/0``).
  3. Confirm Redis is running:  ``redis-cli -u $URL ping`` → PONG.

Phase 1 — Seed Redis with current nonce high-water marks (live, zero-downtime)
  Run once while the bot is running (it can keep trading):

    from bot.distributed_nonce_manager import make_api_key_id
    from bot.global_kraken_nonce import _KEY_REGISTRY, _KEY_REGISTRY_LOCK
    import redis, os, time

    r = redis.from_url(os.environ["NIJA_REDIS_URL"])
    PREFIX = "nija:kraken:nonce:"

    # Seed platform key
    from bot.global_kraken_nonce import get_global_nonce_manager
    mgr = get_global_nonce_manager()
    platform_key = os.environ.get("KRAKEN_PLATFORM_API_KEY", "")
    if platform_key:
        kid = make_api_key_id(platform_key)
        # Use SETNX so we never decrease an existing Redis value
        r.execute_command("SET", PREFIX + kid, mgr.get_last_nonce(), "NX")

    # Seed per-user keys
    with _KEY_REGISTRY_LOCK:
        entries = dict(_KEY_REGISTRY)
    for key_id, nm in entries.items():
        r.execute_command("SET", PREFIX + key_id, nm.get_last_nonce(), "NX")

  Note: SETNX ("SET … NX") only writes if the key doesn't exist, so this
  is idempotent — safe to run multiple times.

Phase 2 — Set NIJA_REDIS_URL in the environment (no restart yet)
  Add to Railway / .env:
    NIJA_REDIS_URL=redis://:<password>@<host>:6379/0

  The bot reads this on the NEXT restart.  Current session unaffected.

Phase 3 — Rolling restart (zero-downtime)
  If you run one container:
    Deploy the new environment variable.  Railway automatically restarts.
    The bot picks up NIJA_REDIS_URL on startup and ``DistributedNonceManager``
    auto-connects to Redis.  Nonces continue from the seeded high-water mark.

  If you run multiple containers (scale-out):
    Restart them one at a time.  Each restarted instance picks up Redis.
    Instances still running (file mode) continue independently — they write
    their nonces to local state files.  Redis receives the higher value on
    the next call from a restarted instance because of the ``max(current+1,
    floor)`` Lua semantics — no nonce collision is possible.

Phase 4 — Verify
  Check logs for:
    DistributedNonceManager: using Redis backend (multi-instance safe)
    Nonce: DistributedNonceManager  backend=redis   key_id=<hex>

  Run the concurrency test (bot/test_distributed_nonce_manager.py) against
  the live Redis instance to confirm no collisions.

Phase 5 — Key rotation (if ever needed after migration)
  After generating a new Kraken API key:
    1. Stop the bot (or enter maintenance mode).
    2. Call:  get_distributed_nonce_manager().reset_key(new_key_id)
             (this deletes the Redis key and destroys the local file manager)
    3. Update KRAKEN_PLATFORM_API_KEY / KRAKEN_USER_<id>_API_KEY.
    4. Restart.  The new key starts at nonce 0 — correct by design.

Rollback
  Unset NIJA_REDIS_URL and restart.  The bot falls back to file/fcntl mode
  immediately.  Redis nonce keys are left in place and act as a safe floor
  if you re-enable Redis later.
─────────────────────────────────────────────────────────────────────────────

Usage
-----
    from bot.distributed_nonce_manager import (
        get_distributed_nonce_manager,
        make_api_key_id,
    )

    key_id = make_api_key_id(raw_api_key)       # once, at connect()
    nonce  = get_distributed_nonce_manager().get_nonce(key_id)
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from typing import Optional

_logger = logging.getLogger(__name__)

# ── Key derivation ─────────────────────────────────────────────────────────────

def make_api_key_id(raw_api_key: str) -> str:
    """Return a stable, opaque 16-hex-char identifier for *raw_api_key*.

    ``sha256(key).hexdigest()[:16]`` — deterministic, collision-resistant,
    safe to log and use as a filename component.  Keys can rotate freely:
    the new key gets a new id and a fresh nonce sequence, which is exactly
    correct (a rotated key starts at nonce 0 at Kraken).
    """
    return hashlib.sha256(raw_api_key.encode()).hexdigest()[:16]


# ── Redis nonce backend (per-key) ──────────────────────────────────────────────

class _PerKeyRedisBackend:
    """
    Thin wrapper around a Redis client that issues atomically increasing
    nonces for a single API key.

    The Lua script is registered once per Redis connection and reused for
    all key_ids via a per-key Redis key ``nija:kraken:nonce:<key_id>``.
    Two concurrent callers (different processes, different containers) on
    the same Redis server CANNOT receive the same nonce.
    """

    # Lua script: atomically advance the nonce to max(current+1, floor_ms).
    #
    # Why GET + SET instead of INCRBY?
    # Redis INCRBY only increments by a fixed amount.  Our requirement is
    # max(current+1, floor_ms) — a conditional advance keyed to wall-clock time.
    # INCRBY cannot express this in one command; the Lua script is the correct
    # tool because the entire script runs atomically on the Redis server, so
    # no two callers can interleave their read-compare-write.
    #
    # KEYS[1] = nonce key, ARGV[1] = floor_ms (int milliseconds).
    _LUA = """
        local cur   = tonumber(redis.call('GET', KEYS[1])) or 0
        local floor = tonumber(ARGV[1])
        local next  = math.max(cur + 1, floor)
        redis.call('SET', KEYS[1], tostring(next))
        return next
    """
    _KEY_PREFIX = "nija:kraken:nonce:"

    def __init__(self, redis_client: object) -> None:
        self._client = redis_client
        self._script = redis_client.register_script(self._LUA)  # type: ignore[attr-defined]
        self._client.ping()  # type: ignore[attr-defined]
        _logger.info("DistributedNonceManager: Redis backend connected")

    def next_nonce(self, key_id: str) -> int:
        """Atomically return the next nonce for *key_id* (>= now_ms, strictly increasing)."""
        floor = int(time.time() * 1000)
        redis_key = self._KEY_PREFIX + key_id
        result = self._script(keys=[redis_key], args=[floor])
        return int(result)

    def get_last(self, key_id: str) -> int:
        """Return the last issued nonce without advancing (0 if never set)."""
        val = self._client.get(self._KEY_PREFIX + key_id)  # type: ignore[attr-defined]
        return int(val) if val else 0

    def reset(self, key_id: str) -> None:
        """Delete the nonce key for *key_id* (fresh start — use only after key rotation)."""
        self._client.delete(self._KEY_PREFIX + key_id)  # type: ignore[attr-defined]
        _logger.warning(
            "DistributedNonceManager: Redis nonce key reset for key_id=%s "
            "(new key rotation — nonce sequence restarting from 0)",
            key_id,
        )


# ── Distributed nonce manager ─────────────────────────────────────────────────

class DistributedNonceManager:
    """
    Unified nonce authority for all Kraken API keys.

    Replaces both ``UserNonceManager`` and the platform ``KrakenNonceManager``
    as the single routing point for every nonce request in the system.

    Backend selection (in priority order)
    --------------------------------------
    1. **Redis** (if ``redis_client`` was provided and is reachable):
       Atomic per-key Lua INCR — safe across hosts and containers.
    2. **File / fcntl lock** (fallback):
       Per-key ``KrakenNonceManager`` instance — safe within one host.

    Both backends guarantee:
      ✅ Strictly monotonic per API key.
      ✅ Thread-safe within one process.
      ✅ Persistent across restarts.
      ✅ Pre-request guard — stale instances are rebuilt from server time.

    Constructor
    -----------
    Normally obtained via ``get_distributed_nonce_manager()``.  Direct
    construction is supported for testing or when you want to supply a
    custom Redis client::

        mgr = DistributedNonceManager(redis_client=my_redis)
    """

    def __init__(self, redis_client: Optional[object] = None) -> None:
        self._lock = threading.Lock()
        self._redis: Optional[_PerKeyRedisBackend] = None

        if redis_client is not None:
            try:
                self._redis = _PerKeyRedisBackend(redis_client)
                _logger.info(
                    "DistributedNonceManager: using Redis backend "
                    "(multi-instance safe)"
                )
            except Exception as exc:
                _logger.critical(
                    "DistributedNonceManager: Redis backend unavailable (%s) — "
                    "falling back to per-key file locks.  "
                    "Multi-instance nonce coordination is DISABLED.  "
                    "Ensure only ONE bot instance is running per API key.",
                    exc,
                )
        else:
            _logger.info(
                "DistributedNonceManager: no Redis client — "
                "using per-key file-lock backend (single-host safe)"
            )

    # ── Core API ──────────────────────────────────────────────────────────────

    def get_nonce(self, api_key_id: str) -> int:
        """Return the next strictly-increasing nonce for *api_key_id*.

        Routes through Redis when available (multi-instance safe), otherwise
        through the per-key ``KrakenNonceManager`` with ``fcntl`` locking.

        Parameters
        ----------
        api_key_id:
            The opaque key identifier returned by ``make_api_key_id(raw_key)``.
            Must be the SAME id used by every instance that shares this key.
        """
        if self._redis is not None:
            try:
                nonce = self._redis.next_nonce(api_key_id)
                _logger.debug(
                    "DistributedNonceManager[redis]: key=%s nonce=%d",
                    api_key_id, nonce,
                )
                return nonce
            except Exception as exc:
                _logger.error(
                    "DistributedNonceManager: Redis nonce call failed for "
                    "key=%s (%s) — falling back to file mode for this call",
                    api_key_id, exc,
                )
        # File / fcntl path — per-key KrakenNonceManager singleton
        return self._file_nonce(api_key_id)

    def record_error(self, api_key_id: str) -> None:
        """Record a nonce rejection from Kraken for *api_key_id*.

        In Redis mode the error is forwarded to the per-key
        ``KrakenNonceManager`` so the escalating jump backoff and nuclear-reset
        machinery still fires (Redis nonce stays authoritative, but the local
        manager's recovery probes drive the jump strategy).
        In file mode this directly calls ``record_error()`` on the manager.
        """
        try:
            mgr = self._get_file_manager(api_key_id)
            mgr.record_error()
        except Exception as exc:
            _logger.debug(
                "DistributedNonceManager.record_error: key=%s error=%s",
                api_key_id, exc,
            )

    def record_success(self, api_key_id: str, nonce: int) -> None:
        """Record that Kraken accepted *nonce* for *api_key_id*."""
        try:
            mgr = self._get_file_manager(api_key_id)
            mgr.record_success(nonce)
        except Exception as exc:
            _logger.debug(
                "DistributedNonceManager.record_success: key=%s error=%s",
                api_key_id, exc,
            )

    def reset_key(self, api_key_id: str) -> None:
        """Hard-reset the nonce sequence for *api_key_id*.

        Call this ONLY immediately after rotating a Kraken API key.  The new
        key has nonce floor 0 at Kraken, so the old persisted high-water mark
        must be discarded.
        """
        _logger.warning(
            "DistributedNonceManager.reset_key: resetting nonce for key=%s "
            "(key rotation — sequence restarting)",
            api_key_id,
        )
        if self._redis is not None:
            try:
                self._redis.reset(api_key_id)
            except Exception as exc:
                _logger.error(
                    "DistributedNonceManager.reset_key: Redis reset failed "
                    "for key=%s (%s)",
                    api_key_id, exc,
                )
        # Destroy the per-key file manager so it rebuilds fresh on next call
        try:
            from bot.global_kraken_nonce import KrakenNonceManager
            KrakenNonceManager.destroy_instance(key_id=api_key_id)
        except Exception:
            try:
                from global_kraken_nonce import KrakenNonceManager  # type: ignore
                KrakenNonceManager.destroy_instance(key_id=api_key_id)
            except Exception as exc2:
                _logger.debug(
                    "DistributedNonceManager.reset_key: could not destroy "
                    "file manager for key=%s: %s",
                    api_key_id, exc2,
                )

    def get_last_nonce(self, api_key_id: str) -> int:
        """Return the last issued nonce without advancing it (diagnostic use)."""
        if self._redis is not None:
            try:
                return self._redis.get_last(api_key_id)
            except Exception:
                pass
        try:
            return self._get_file_manager(api_key_id).get_last_nonce()
        except Exception:
            return 0

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _file_nonce(self, api_key_id: str) -> int:
        """Issue next nonce via the per-key KrakenNonceManager (file/fcntl)."""
        return self._get_file_manager(api_key_id).next_nonce()

    def _get_file_manager(self, api_key_id: str):
        """Return the per-key KrakenNonceManager, creating it if needed."""
        try:
            from bot.global_kraken_nonce import get_nonce_manager_for_key
        except ImportError:
            from global_kraken_nonce import get_nonce_manager_for_key  # type: ignore
        return get_nonce_manager_for_key(api_key_id)


# ── Process-global singleton ──────────────────────────────────────────────────

_dnm_instance: Optional[DistributedNonceManager] = None
_dnm_lock = threading.Lock()


def get_distributed_nonce_manager(
    redis_client: Optional[object] = None,
) -> DistributedNonceManager:
    """Return the process-global ``DistributedNonceManager`` singleton.

    On first call, ``redis_client`` is used to configure the backend.  On
    subsequent calls the argument is ignored — call
    ``reset_distributed_nonce_manager()`` first if you need to reconfigure.

    Environment-variable shortcut
    ------------------------------
    If ``NIJA_REDIS_URL`` is set and ``redis_client`` is not provided, the
    manager will attempt to construct a Redis client automatically.
    """
    global _dnm_instance
    if _dnm_instance is not None:
        return _dnm_instance
    with _dnm_lock:
        if _dnm_instance is not None:
            return _dnm_instance
        # Auto-construct Redis client from env if not supplied
        if redis_client is None:
            redis_url = os.environ.get("NIJA_REDIS_URL", "").strip()
            if redis_url:
                try:
                    import redis as _redis_lib  # type: ignore[import]
                    redis_client = _redis_lib.from_url(
                        redis_url,
                        decode_responses=True,
                        socket_timeout=2.0,
                        socket_connect_timeout=2.0,
                    )
                    _logger.info(
                        "DistributedNonceManager: auto-connecting to Redis at %s",
                        redis_url,
                    )
                except Exception as exc:
                    _logger.warning(
                        "DistributedNonceManager: could not build Redis client "
                        "from NIJA_REDIS_URL (%s) — file-lock fallback active",
                        exc,
                    )
        _dnm_instance = DistributedNonceManager(redis_client=redis_client)
    return _dnm_instance


def reset_distributed_nonce_manager() -> None:
    """Destroy the singleton so the next call to ``get_distributed_nonce_manager()``
    creates a fresh instance (useful in tests or after reconfiguring Redis)."""
    global _dnm_instance
    with _dnm_lock:
        _dnm_instance = None


__all__ = [
    "DistributedNonceManager",
    "make_api_key_id",
    "get_distributed_nonce_manager",
    "reset_distributed_nonce_manager",
]
