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
import socket
import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from bot.redis_env import get_redis_url

_logger = logging.getLogger(__name__)


def _env_true(name: str, default: str = "0") -> bool:
    """Return True if env var *name* is set to a truthy value."""
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


# The writer lease must outlive ordinary gaps between Kraken private calls.
# A 15s default was shorter than normal startup/watchdog idle periods, which
# caused the same process to reacquire a fresh lease version and hard-stop on
# the next nonce request. Keep the override env var, but default to 2 minutes
# so routine idle windows do not look like split-brain.
_REDIS_LEASE_TTL_MS = max(1_000, int(os.environ.get("NIJA_REDIS_LEASE_TTL_MS", "120000")))
_STRICT_REDIS_LEASE = (
    _env_true("NIJA_STRICT_REDIS_LEASE", "1")
    and not _env_true("NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK", "0")
)
_REDIS_LEASE_ACQUIRE_TIMEOUT_S = max(
    0.0, float(os.environ.get("NIJA_REDIS_LEASE_ACQUIRE_TIMEOUT_S", "90"))
)
_REDIS_LEASE_ACQUIRE_POLL_S = max(
    0.1, float(os.environ.get("NIJA_REDIS_LEASE_ACQUIRE_POLL_S", "0.5"))
)
_REDIS_LEASE_WAIT_LOG_INTERVAL_S = max(
    0.5, float(os.environ.get("NIJA_REDIS_LEASE_WAIT_LOG_INTERVAL_S", "30"))
)
_PROCESS_STARTUP_HASH = uuid.uuid4().hex[:16]


def _compute_initial_lease_wait_budget_s(
    config_timeout_s: float,
    holder_ttl_ms: int,
    poll_s: float,
) -> float:
    """Return the cold-start lease wait budget in seconds.

    Startup must wait at least as long as the currently observed Redis lease
    TTL. Otherwise a stale holder can still be counting down when the local
    acquire timeout expires, producing a false hard-stop even though the lease
    would naturally become available moments later.
    """
    wait_budget_s = max(0.0, float(config_timeout_s))
    if holder_ttl_ms > 0:
        wait_budget_s = max(wait_budget_s, (holder_ttl_ms / 1000.0) + max(0.05, float(poll_s)))
    return wait_budget_s

# ── Nonce issuance authorization check (lazy reference) ──────────────────────
# Resolved on first use to avoid any import-order issues.  Returns True in
# degraded / unavailable mode so the gate degrades gracefully.
_nonce_auth_fn: Optional[Callable[[], bool]] = None
_nonce_auth_fn_lock = threading.Lock()


def _get_nonce_auth() -> bool:
    """Return True if nonce issuance is currently authorized."""
    global _nonce_auth_fn
    if _nonce_auth_fn is None:
        with _nonce_auth_fn_lock:
            if _nonce_auth_fn is None:
                try:
                    try:
                        from bot.global_kraken_nonce import (
                            is_nonce_issuance_authorized,
                        )
                    except ImportError:
                        from global_kraken_nonce import (  # type: ignore[import]
                            is_nonce_issuance_authorized,
                        )
                    _nonce_auth_fn = is_nonce_issuance_authorized
                except ImportError:
                    _logger.critical(
                        "DistributedNonceManager: could not import "
                        "is_nonce_issuance_authorized from global_kraken_nonce — "
                        "nonce authorization gate is DISABLED (degraded mode). "
                        "All nonce issuance will be allowed regardless of FSM state. "
                        "Ensure global_kraken_nonce is installed and importable."
                    )
                    _nonce_auth_fn = lambda: True  # noqa: E731  # degraded: gate disabled
    return _nonce_auth_fn()


def _detect_container_id() -> str:
    """Best-effort container id for process fingerprinting."""
    # Kubernetes / Docker often provide HOSTNAME as the pod/container id.
    host = os.environ.get("HOSTNAME", "").strip()
    if len(host) >= 12:
        return host
    try:
        with open("/proc/self/cgroup", "r", encoding="utf-8") as fh:
            for line in fh:
                seg = line.strip().split("/")[-1]
                if len(seg) >= 12:
                    return seg
    except Exception:
        pass
    return "unknown"


def _build_process_fingerprint() -> str:
    """Return a stable-per-process fingerprint for lease ownership metadata."""
    pid = os.getpid()
    host = socket.gethostname()
    container_id = _detect_container_id()
    return f"pid={pid}|host={host}|container={container_id}|startup={_PROCESS_STARTUP_HASH}"


def _redact_redis_url(redis_url: str) -> str:
    """Return a logging-safe Redis URL with credentials removed."""
    try:
        parts = urlsplit(redis_url)
        if not parts.scheme:
            return "<configured>"
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        safe_netloc = f"<redacted>@{host}{port}" if parts.username or parts.password else f"{host}{port}"
        return urlunsplit((parts.scheme, safe_netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return "<configured>"

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
    _LEASE_OWNER_PREFIX = "nija:kraken:writer:owner:"
    _LEASE_VERSION_PREFIX = "nija:kraken:writer:lease_version:"
    _LEASE_VERSION_COUNTER_PREFIX = "nija:kraken:writer:version_counter:"
    _LEASE_FINGERPRINT_PREFIX = "nija:kraken:writer:fingerprint:"

    _LEASE_LUA = """
        local owner_key = KEYS[1]
        local version_key = KEYS[2]
        local counter_key = KEYS[3]
        local fingerprint_key = KEYS[4]
        local owner = ARGV[1]
        local ttl = tonumber(ARGV[2])
        local fingerprint = ARGV[3]

        local current_owner = redis.call('GET', owner_key)
        if not current_owner then
            local version = redis.call('INCR', counter_key)
            redis.call('SET', owner_key, owner, 'PX', ttl)
            redis.call('SET', version_key, tostring(version), 'PX', ttl)
            redis.call('SET', fingerprint_key, fingerprint, 'PX', ttl)
            return {1, version, owner}
        end

        if current_owner == owner then
            local version = tonumber(redis.call('GET', version_key))
            if not version then
                version = redis.call('INCR', counter_key)
            end
            redis.call('PEXPIRE', owner_key, ttl)
            redis.call('SET', version_key, tostring(version), 'PX', ttl)
            redis.call('SET', fingerprint_key, fingerprint, 'PX', ttl)
            return {1, version, owner}
        end

        local current_version = tonumber(redis.call('GET', version_key)) or 0
        return {0, current_version, current_owner}
    """
    _NEXT_WITH_FENCE_LUA = """
        local nonce_key = KEYS[1]
        local owner_key = KEYS[2]
        local version_key = KEYS[3]
        local floor = tonumber(ARGV[1])
        local expected_owner = ARGV[2]
        local expected_version = tonumber(ARGV[3])

        local current_owner = redis.call('GET', owner_key)
        local current_version = tonumber(redis.call('GET', version_key)) or 0

        if current_owner ~= expected_owner then
            return {0, "OWNER_MISMATCH", current_version, current_owner or ""}
        end
        if current_version ~= expected_version then
            return {0, "VERSION_MISMATCH", current_version, current_owner or ""}
        end

        local cur = tonumber(redis.call('GET', nonce_key)) or 0
        local next = math.max(cur + 1, floor)
        redis.call('SET', nonce_key, tostring(next))
        return {1, next, current_version, current_owner}
    """

    @dataclass
    class _LeaseState:
        version: int
        owner_id: str

    def __init__(
        self,
        redis_client: object,
        owner_id: str,
        owner_fingerprint: str,
        lease_ttl_ms: int = _REDIS_LEASE_TTL_MS,
        strict_lease: bool = _STRICT_REDIS_LEASE,
    ) -> None:
        self._client = redis_client
        self._script = redis_client.register_script(self._LUA)  # type: ignore[attr-defined]
        self._lease_script = redis_client.register_script(self._LEASE_LUA)  # type: ignore[attr-defined]
        self._next_with_fence_script = redis_client.register_script(  # type: ignore[attr-defined]
            self._NEXT_WITH_FENCE_LUA
        )
        self._client.ping()  # type: ignore[attr-defined]
        self._owner_id = owner_id
        self._owner_fingerprint = owner_fingerprint
        self._lease_ttl_ms = lease_ttl_ms
        self._strict_lease = strict_lease
        self._lease_by_key: Dict[str, _PerKeyRedisBackend._LeaseState] = {}
        self._wait_log_next_at: Dict[str, float] = {}
        self._wait_log_lock = threading.Lock()
        _logger.info("DistributedNonceManager: Redis backend connected")

    def _should_emit_wait_log(self, key_id: str, now_monotonic: float, *, force: bool = False) -> bool:
        """Return True when the next wait log for *key_id* should be emitted."""
        with self._wait_log_lock:
            next_allowed = self._wait_log_next_at.get(key_id, 0.0)
            if not force and now_monotonic < next_allowed:
                return False
            self._wait_log_next_at[key_id] = now_monotonic + _REDIS_LEASE_WAIT_LOG_INTERVAL_S
            return True

    def _clear_wait_log_gate(self, key_id: str) -> None:
        """Clear per-key wait-log gate after successful lease acquisition."""
        with self._wait_log_lock:
            self._wait_log_next_at.pop(key_id, None)

    def next_nonce(self, key_id: str) -> int:
        """Atomically return the next nonce for *key_id* (>= now_ms, strictly increasing)."""
        lease_version = self._ensure_writer_lease(key_id)
        floor = int(time.time() * 1000)
        redis_key = self._KEY_PREFIX + key_id
        owner_key = self._LEASE_OWNER_PREFIX + key_id
        version_key = self._LEASE_VERSION_PREFIX + key_id
        result = self._next_with_fence_script(
            keys=[redis_key, owner_key, version_key],
            args=[floor, self._owner_id, lease_version],
        )
        if int(result[0]) != 1:
            raise RuntimeError(
                "Redis fencing check rejected nonce issuance "
                f"(key_id={key_id}, reason={result[1]}, lease_version={result[2]}, owner={result[3]})"
            )
        return int(result[1])

    def get_last(self, key_id: str) -> int:
        """Return the last issued nonce without advancing (0 if never set)."""
        val = self._client.get(self._KEY_PREFIX + key_id)  # type: ignore[attr-defined]
        return int(val) if val else 0

    def reset(self, key_id: str) -> None:
        """Delete the nonce key for *key_id* (fresh start — use only after key rotation)."""
        self._client.delete(self._KEY_PREFIX + key_id)  # type: ignore[attr-defined]
        self._lease_by_key.pop(key_id, None)
        _logger.warning(
            "DistributedNonceManager: Redis nonce key reset for key_id=%s "
            "(new key rotation — nonce sequence restarting from 0)",
            key_id,
        )

    def _ensure_writer_lease(self, key_id: str) -> int:
        """
        Acquire/renew strict Redis writer lease and enforce fencing token stability.

        Fail closed when lease ownership changes or when fencing token rotates
        within the same process lifetime.
        """
        owner_key = self._LEASE_OWNER_PREFIX + key_id
        version_key = self._LEASE_VERSION_PREFIX + key_id
        counter_key = self._LEASE_VERSION_COUNTER_PREFIX + key_id
        fingerprint_key = self._LEASE_FINGERPRINT_PREFIX + key_id
        prev = self._lease_by_key.get(key_id)

        def _run_lease_script() -> tuple[bool, int, str]:
            _result = self._lease_script(
                keys=[owner_key, version_key, counter_key, fingerprint_key],
                args=[self._owner_id, self._lease_ttl_ms, self._owner_fingerprint],
            )
            _granted = int(_result[0]) == 1
            _lease_version = int(_result[1])
            _current_owner = str(_result[2])
            return _granted, _lease_version, _current_owner

        granted, lease_version, current_owner = _run_lease_script()
        if not granted:
            # Startup safety: if this process has not held the lease yet, wait
            # through the observed holder TTL for the current holder to
            # release/expire before failing.
            # Runtime safety: if we previously held a lease and lost it, fail
            # closed immediately to avoid split-brain writes.
            if prev is None and _REDIS_LEASE_ACQUIRE_TIMEOUT_S > 0.0:
                initial_holder_ttl_ms = -1
                try:
                    initial_holder_ttl_ms = int(self._client.pttl(owner_key))  # type: ignore[attr-defined]
                except Exception:
                    pass
                wait_budget_s = _compute_initial_lease_wait_budget_s(
                    _REDIS_LEASE_ACQUIRE_TIMEOUT_S,
                    initial_holder_ttl_ms,
                    _REDIS_LEASE_ACQUIRE_POLL_S,
                )
                deadline = time.monotonic() + wait_budget_s
                wait_started_at = time.monotonic()
                if self._should_emit_wait_log(key_id, wait_started_at, force=True):
                    _logger.warning(
                        "DistributedNonceManager: Redis writer lease busy at startup "
                        "(key=%s owner=%s lease_version=%d initial_holder_ttl_ms=%d wait_budget=%.1fs)",
                        key_id,
                        current_owner,
                        lease_version,
                        initial_holder_ttl_ms,
                        wait_budget_s,
                    )
                while time.monotonic() < deadline and not granted:
                    now = time.monotonic()
                    remaining = deadline - now
                    holder_ttl_ms = -1
                    try:
                        holder_ttl_ms = int(self._client.pttl(owner_key))  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    force_terminal_log = remaining <= (_REDIS_LEASE_ACQUIRE_POLL_S + 0.05)
                    if self._should_emit_wait_log(key_id, now, force=force_terminal_log):
                        _logger.info(
                            "DistributedNonceManager: waiting for Redis writer lease "
                            "(key=%s owner=%s lease_version=%d holder_ttl_ms=%d remaining=%.1fs wait_budget=%.1fs)",
                            key_id,
                            current_owner,
                            lease_version,
                            holder_ttl_ms,
                            remaining,
                            wait_budget_s,
                        )
                    time.sleep(min(_REDIS_LEASE_ACQUIRE_POLL_S, max(0.05, remaining)))
                    granted, lease_version, current_owner = _run_lease_script()

                if granted:
                    self._clear_wait_log_gate(key_id)
                    _logger.info(
                        "DistributedNonceManager: Redis writer lease became available "
                        "(key=%s lease_version=%d waited=%.1fs)",
                        key_id,
                        lease_version,
                        max(0.0, time.monotonic() - wait_started_at),
                    )

            if not granted:
                raise RuntimeError(
                    "Redis writer lease rejected "
                    f"(key_id={key_id}, owner={current_owner}, lease_version={lease_version})"
                )
        if prev is None:
            self._lease_by_key[key_id] = self._LeaseState(version=lease_version, owner_id=self._owner_id)
            _logger.info(
                "DistributedNonceManager: Redis writer lease acquired key=%s lease_version=%d owner=%s",
                key_id,
                lease_version,
                self._owner_fingerprint,
            )
            return lease_version

        # Fencing rule: once a process has a lease version, any version rotation
        # means lease continuity was lost (TTL expiry / partition / failover).
        if prev.version != lease_version:
            msg = (
                "Redis writer lease fencing token changed "
                f"(key_id={key_id}, prev={prev.version}, new={lease_version}). "
                "Hard-stopping to prevent split-brain writes."
            )
            if self._strict_lease:
                raise RuntimeError(msg)
            _logger.critical(msg)
            self._lease_by_key[key_id] = self._LeaseState(version=lease_version, owner_id=self._owner_id)
        return lease_version

    def ensure_writer_lease(self, key_id: str) -> int:
        """Public wrapper around lease acquire/renew + fencing validation."""
        return self._ensure_writer_lease(key_id)


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
        self._owner_id = str(uuid.uuid4())
        self._owner_fingerprint = _build_process_fingerprint()
        self._strict_redis_lease = _STRICT_REDIS_LEASE

        if redis_client is not None:
            try:
                self._redis = _PerKeyRedisBackend(
                    redis_client=redis_client,
                    owner_id=self._owner_id,
                    owner_fingerprint=self._owner_fingerprint,
                    lease_ttl_ms=_REDIS_LEASE_TTL_MS,
                    strict_lease=self._strict_redis_lease,
                )
                _logger.info(
                    "DistributedNonceManager: using Redis backend "
                    "(multi-instance safe, strict_lease=%s, lease_ttl_ms=%d, owner=%s)",
                    self._strict_redis_lease,
                    _REDIS_LEASE_TTL_MS,
                    self._owner_fingerprint,
                )
            except Exception as exc:
                if self._strict_redis_lease:
                    _logger.critical(
                        "DistributedNonceManager: strict Redis lease required but unavailable (%s). "
                        "Failing closed to prevent split-brain.",
                        exc,
                    )
                    raise
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

        Raises ``RuntimeError`` if the startup FSM has revoked nonce issuance
        (FAILED / IDLE state) — hard fail-closed instead of silently issuing
        a stale or invalid nonce.

        Parameters
        ----------
        api_key_id:
            The opaque key identifier returned by ``make_api_key_id(raw_key)``.
            Must be the SAME id used by every instance that shares this key.
        """
        # Hard gate: fail immediately if the FSM has revoked nonce issuance.
        if not _get_nonce_auth():
            raise RuntimeError(
                f"DistributedNonceManager.get_nonce: nonce issuance not authorized "
                f"(key={api_key_id}) — startup FSM is in FAILED/IDLE state; "
                "wait for NONCE_READY / CONNECTED before issuing nonces"
            )
        if self._redis is not None:
            try:
                nonce = self._redis.next_nonce(api_key_id)
                return nonce
            except Exception as exc:
                if self._strict_redis_lease:
                    raise RuntimeError(
                        "DistributedNonceManager: strict Redis lease enforcement blocked nonce issuance "
                        f"for key={api_key_id}: {exc}"
                    ) from exc
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

    def ensure_writer_lock(self, api_key_id: str) -> None:
        """
        Ensure the runtime single-writer lease is held for *api_key_id*.

        In strict Redis mode this fails closed if lease acquisition/renewal
        fails, guaranteeing single-writer lock ownership is validated at runtime.
        """
        if self._redis is None:
            return
        self._redis.ensure_writer_lease(api_key_id)

    def can_issue_nonce(self, api_key_id: str = "") -> bool:
        """
        Return True only when nonce issuance is currently safe for *api_key_id*.

        This combines the startup-FSM authorization gate with the per-key
        PID-lock ownership gate exposed by the file-backed nonce manager.
        """
        if not _get_nonce_auth():
            return False
        if not api_key_id:
            return False
        try:
            return bool(self._get_file_manager(api_key_id).can_issue_nonce())
        except Exception:
            return False

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
    If a supported Redis URL environment variable is set and ``redis_client``
    is not provided, the manager will attempt to construct a Redis client
    automatically.
    """
    global _dnm_instance
    if _dnm_instance is not None:
        return _dnm_instance
    with _dnm_lock:
        if _dnm_instance is not None:
            return _dnm_instance
        # Auto-construct Redis client from env if not supplied
        if redis_client is None:
            redis_url = get_redis_url()
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
                        _redact_redis_url(redis_url),
                    )
                except Exception as exc:
                    _logger.warning(
                        "DistributedNonceManager: could not build Redis client "
                        "from configured Redis URL (%s) — file-lock fallback active",
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
