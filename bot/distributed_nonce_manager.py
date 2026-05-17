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
  3. Confirm Redis is running:  ``redis-cli -h <host> -p <port> -a "$REDIS_PASSWORD" --tls --insecure ping`` → PONG.

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
             (this re-anchors Redis to a fresh monotonic floor and destroys the local file manager)
    3. Update KRAKEN_PLATFORM_API_KEY / KRAKEN_USER_<id>_API_KEY.
    4. Restart.  The new key starts from a fresh near-now floor.

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
import importlib
import logging
import os
import random
import socket
import threading
import time
import uuid
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from bot.redis_env import get_redis_url
from bot.redis_runtime import connect_redis_with_fallback

_logger = logging.getLogger(__name__)


def _env_true(name: str, default: str = "0") -> bool:
    """Return True if env var *name* is set to a truthy value."""
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _live_mode_active() -> bool:
    """Return True when runtime is in live-capital mode."""
    return _env_true("LIVE_CAPITAL_VERIFIED", "0")


# Writer leases must remain stable between renewals while avoiding rapid churn.
# Clamp TTL to 10-60s to tolerate real-world latency spikes without flapping.
# Renew at ~1/3 of TTL (default 0.333) to minimize expiry risk.
_REDIS_LEASE_TTL_MIN_MS = 10_000
_REDIS_LEASE_TTL_MAX_MS = 60_000
_REDIS_LEASE_TTL_DEFAULT_MS = 60_000
try:
    _lease_ttl_raw = int(
        os.environ.get("NIJA_REDIS_LEASE_TTL_MS", str(_REDIS_LEASE_TTL_DEFAULT_MS)) or _REDIS_LEASE_TTL_DEFAULT_MS
    )
except (TypeError, ValueError):
    _lease_ttl_raw = _REDIS_LEASE_TTL_DEFAULT_MS
_REDIS_LEASE_TTL_MS = min(_REDIS_LEASE_TTL_MAX_MS, max(_REDIS_LEASE_TTL_MIN_MS, _lease_ttl_raw))
_STRICT_REDIS_LEASE = (
    _env_true("NIJA_STRICT_REDIS_LEASE", "1")
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
_REDIS_LEASE_FORCE_TAKEOVER = _env_true("NIJA_REDIS_LEASE_FORCE_TAKEOVER", "0")
_REDIS_LEASE_FORCE_TAKEOVER_TIMEOUT_S = max(
    0.0, float(os.environ.get("NIJA_REDIS_LEASE_FORCE_TAKEOVER_TIMEOUT_S", "0"))
)
_REDIS_LEASE_FORCE_TAKEOVER_REFRESH_DELTA_MS = max(
    0, int(os.environ.get("NIJA_REDIS_LEASE_FORCE_TAKEOVER_REFRESH_DELTA_MS", "250"))
)
_REDIS_NONCE_RESET_BUFFER_MS = max(
    0, int(os.environ.get("NIJA_REDIS_NONCE_RESET_BUFFER_MS", "5000"))
)
_PROCESS_STARTUP_HASH = uuid.uuid4().hex[:16]
try:
    _REDIS_LEASE_STARTUP_BACKOFF_MIN_S = max(
        0.0, float(os.environ.get("NIJA_REDIS_LEASE_STARTUP_BACKOFF_MIN_S", "5") or "5")
    )
except (TypeError, ValueError):
    _REDIS_LEASE_STARTUP_BACKOFF_MIN_S = 5.0
try:
    _REDIS_LEASE_STARTUP_BACKOFF_MAX_S = max(
        0.0, float(os.environ.get("NIJA_REDIS_LEASE_STARTUP_BACKOFF_MAX_S", "15") or "15")
    )
except (TypeError, ValueError):
    _REDIS_LEASE_STARTUP_BACKOFF_MAX_S = 15.0
if _REDIS_LEASE_STARTUP_BACKOFF_MAX_S < _REDIS_LEASE_STARTUP_BACKOFF_MIN_S:
    _REDIS_LEASE_STARTUP_BACKOFF_MIN_S, _REDIS_LEASE_STARTUP_BACKOFF_MAX_S = (
        _REDIS_LEASE_STARTUP_BACKOFF_MAX_S,
        _REDIS_LEASE_STARTUP_BACKOFF_MIN_S,
    )
try:
    _REDIS_LEASE_RENEWAL_FRACTION = float(
        os.environ.get("NIJA_REDIS_LEASE_RENEWAL_FRACTION", "0.333") or "0.333"
    )
except (TypeError, ValueError):
    _REDIS_LEASE_RENEWAL_FRACTION = 0.333
# TTL/3 default minimizes expiry risk; override via env if needed.
if _REDIS_LEASE_RENEWAL_FRACTION < 0.0:
    _REDIS_LEASE_RENEWAL_FRACTION = 0.0
elif _REDIS_LEASE_RENEWAL_FRACTION > 0.9:
    _REDIS_LEASE_RENEWAL_FRACTION = 0.9
try:
    _REDIS_LEASE_RENEWAL_MIN_S = max(
        0.5, float(os.environ.get("NIJA_REDIS_LEASE_RENEWAL_MIN_S", "1.5") or "1.5")
    )
except (TypeError, ValueError):
    _REDIS_LEASE_RENEWAL_MIN_S = 1.5
try:
    _REDIS_LEASE_STATUS_LOG_INTERVAL_S = max(
        0.0, float(os.environ.get("NIJA_REDIS_LEASE_STATUS_LOG_INTERVAL_S", "30") or "30")
    )
except (TypeError, ValueError):
    _REDIS_LEASE_STATUS_LOG_INTERVAL_S = 30.0


def _runtime_strict_redis_lease() -> bool:
    """Resolve strict lease mode using current runtime env flags.

    This is evaluated at manager construction time (not import time) so a
    startup degraded-mode decision can be propagated safely.
    """
    _strict_requested = (
        _env_true("NIJA_STRICT_REDIS_LEASE", "1")
    )
    return _strict_requested


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


def _resolve_instance_id() -> str:
    """Return a best-effort instance id for logs (Railway/container aware)."""
    try:
        try:
            from bot.instance_identity import current_instance_identity
        except ImportError:
            from instance_identity import current_instance_identity  # type: ignore[import]
        identity = current_instance_identity()
        return str(identity.get("instance_id", "") or "")
    except Exception:
        return ""


def _nonce_debug_hooks_enabled() -> bool:
    """Return True when nonce trace hooks are enabled."""
    return _env_true("NIJA_NONCE_DEBUG_HOOKS", "0")


def _emit_nonce_debug_hook(event: str, **fields: object) -> None:
    """Emit an opt-in structured nonce debug log event."""
    if not _nonce_debug_hooks_enabled():
        return
    _parts = []
    for _key, _value in fields.items():
        _safe = str(_value).replace("\n", "\\n").replace("\r", "\\r")
        _parts.append(f"{_key}={_safe}")
    _logger.warning("NONCE_DEBUG event=%s %s", event, " ".join(_parts))


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


def _require_api_key_id(api_key_id: str) -> str:
    """Validate and normalize API key identifiers used by nonce authority."""
    normalized = str(api_key_id or "").strip()
    if not normalized:
        raise ValueError("api_key_id is required and cannot be empty")
    return normalized

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

    # Lua scripts execute atomically on Redis; internal read/write sequences do not interleave.
    # Renewal logic is duplicated across lease scripts to keep each Lua script self-contained.
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
                local counter_created = redis.call('SETNX', counter_key, 0)
                if counter_created == 1 then
                    version = 0
                else
                    version = tonumber(redis.call('GET', counter_key)) or 0
                end
                local set_ok = redis.call('SET', version_key, tostring(version), 'PX', ttl, 'NX')
                if not set_ok then
                    local existing_version = tonumber(redis.call('GET', version_key))
                    if existing_version then
                        version = existing_version
                        redis.call('PEXPIRE', version_key, ttl)
                    end
                end
            else
                redis.call('PEXPIRE', version_key, ttl)
            end
            if redis.call('EXISTS', fingerprint_key) == 1 then
                redis.call('PEXPIRE', fingerprint_key, ttl)
            else
                local fp_set = redis.call('SET', fingerprint_key, fingerprint, 'PX', ttl, 'NX')
                if not fp_set then
                    local existing_fp = redis.call('GET', fingerprint_key)
                    if existing_fp == fingerprint then
                        redis.call('PEXPIRE', fingerprint_key, ttl)
                    end
                end
            end
            redis.call('PEXPIRE', owner_key, ttl)
            return {1, version, owner}
        end

        local current_version = tonumber(redis.call('GET', version_key)) or 0
        return {0, current_version, current_owner}
    """
    _LEASE_RELEASE_LUA = """
        local owner_key = KEYS[1]
        local version_key = KEYS[2]
        local fingerprint_key = KEYS[3]
        local owner = ARGV[1]

        local current_owner = redis.call('GET', owner_key)
        if not current_owner then
            return 0
        end
        if current_owner ~= owner then
            return 0
        end
        redis.call('DEL', owner_key)
        redis.call('DEL', version_key)
        redis.call('DEL', fingerprint_key)
        return 1
    """
    # Keep renewal semantics mirrored with _LEASE_LUA for consistency (update both together).
    _LEASE_FORCE_LUA = """
        local owner_key = KEYS[1]
        local version_key = KEYS[2]
        local counter_key = KEYS[3]
        local fingerprint_key = KEYS[4]
        local owner = ARGV[1]
        local ttl = tonumber(ARGV[2])
        local fingerprint = ARGV[3]
        local force = tonumber(ARGV[4]) or 0

        local current_owner = redis.call('GET', owner_key)
        if current_owner and current_owner == owner then
            local version = tonumber(redis.call('GET', version_key))
            if not version then
                local counter_created = redis.call('SETNX', counter_key, 0)
                if counter_created == 1 then
                    version = 0
                else
                    version = tonumber(redis.call('GET', counter_key)) or 0
                end
                local set_ok = redis.call('SET', version_key, tostring(version), 'PX', ttl, 'NX')
                if not set_ok then
                    local existing_version = tonumber(redis.call('GET', version_key))
                    if existing_version then
                        version = existing_version
                        redis.call('PEXPIRE', version_key, ttl)
                    end
                end
            else
                redis.call('PEXPIRE', version_key, ttl)
            end
            if redis.call('EXISTS', fingerprint_key) == 1 then
                redis.call('PEXPIRE', fingerprint_key, ttl)
            else
                local fp_set = redis.call('SET', fingerprint_key, fingerprint, 'PX', ttl, 'NX')
                if not fp_set then
                    local existing_fp = redis.call('GET', fingerprint_key)
                    if existing_fp == fingerprint then
                        redis.call('PEXPIRE', fingerprint_key, ttl)
                    end
                end
            end
            redis.call('PEXPIRE', owner_key, ttl)
            return {1, version, current_owner}
        end
        if current_owner and current_owner ~= owner and force ~= 1 then
            local current_version = tonumber(redis.call('GET', version_key)) or 0
            return {0, current_version, current_owner}
        end

        local version = redis.call('INCR', counter_key)
        redis.call('SET', owner_key, owner, 'PX', ttl)
        redis.call('SET', version_key, tostring(version), 'PX', ttl)
        redis.call('SET', fingerprint_key, fingerprint, 'PX', ttl)
        return {1, version, current_owner or ""}
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
        stable_since: float
        last_renewed_at: float

    def __init__(
        self,
        redis_client: object,
        owner_id: str,
        owner_fingerprint: str,
        owner_instance_id: str,
        lease_ttl_ms: int = _REDIS_LEASE_TTL_MS,
        strict_lease: bool = _STRICT_REDIS_LEASE,
    ) -> None:
        self._client = redis_client
        self._script = redis_client.register_script(self._LUA)  # type: ignore[attr-defined]
        self._lease_script = redis_client.register_script(self._LEASE_LUA)  # type: ignore[attr-defined]
        self._lease_release_script = redis_client.register_script(self._LEASE_RELEASE_LUA)  # type: ignore[attr-defined]
        self._lease_force_script = redis_client.register_script(self._LEASE_FORCE_LUA)  # type: ignore[attr-defined]
        self._next_with_fence_script = redis_client.register_script(  # type: ignore[attr-defined]
            self._NEXT_WITH_FENCE_LUA
        )
        self._client.ping()  # type: ignore[attr-defined]
        self._owner_id = owner_id
        self._owner_fingerprint = owner_fingerprint
        self._owner_instance_id = owner_instance_id
        self._lease_ttl_ms = lease_ttl_ms
        self._strict_lease = strict_lease
        self._lease_by_key: Dict[str, _PerKeyRedisBackend._LeaseState] = {}
        self._wait_log_next_at: Dict[str, float] = {}
        self._wait_log_lock = threading.Lock()
        self._startup_backoff_done: set[str] = set()
        self._lease_heartbeat_threads: Dict[str, threading.Thread] = {}
        self._lease_heartbeat_stop: Dict[str, threading.Event] = {}
        self._lease_status_last_log: Dict[str, float] = {}
        if _REDIS_LEASE_RENEWAL_FRACTION > 0:
            self._lease_renewal_interval_s = max(
                _REDIS_LEASE_RENEWAL_MIN_S,
                (self._lease_ttl_ms / 1000.0) * _REDIS_LEASE_RENEWAL_FRACTION,
            )
        else:
            self._lease_renewal_interval_s = 0.0
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

    def _maybe_apply_startup_backoff(self, key_id: str) -> None:
        """Sleep once per key to desynchronize lease acquisition at startup."""
        if key_id in self._startup_backoff_done:
            return
        self._startup_backoff_done.add(key_id)
        if _REDIS_LEASE_STARTUP_BACKOFF_MAX_S <= 0:
            return
        delay = random.uniform(
            _REDIS_LEASE_STARTUP_BACKOFF_MIN_S,
            _REDIS_LEASE_STARTUP_BACKOFF_MAX_S,
        )
        if delay <= 0:
            return
        _logger.warning(
            "DistributedNonceManager: startup backoff before Redis writer lease acquisition "
            "(key=%s delay=%.1fs)",
            key_id,
            delay,
        )
        time.sleep(delay)

    def _ensure_lease_heartbeat(self, key_id: str) -> None:
        """Start a background renewal loop to keep the writer lease alive."""
        if self._lease_renewal_interval_s <= 0:
            return
        if key_id in self._lease_heartbeat_threads:
            return
        stop_event = threading.Event()
        self._lease_heartbeat_stop[key_id] = stop_event
        thread = threading.Thread(
            target=self._lease_heartbeat_loop,
            args=(key_id, stop_event, self._lease_renewal_interval_s),
            daemon=True,
            name=f"RedisNonceLeaseHeartbeat-{key_id}",
        )
        self._lease_heartbeat_threads[key_id] = thread
        thread.start()

    def _stop_lease_heartbeat(self, key_id: str) -> None:
        """Stop the heartbeat loop for a key (if running)."""
        stop_event = self._lease_heartbeat_stop.pop(key_id, None)
        if stop_event is not None:
            stop_event.set()
        self._lease_heartbeat_threads.pop(key_id, None)

    def _lease_heartbeat_loop(
        self,
        key_id: str,
        stop_event: threading.Event,
        interval_s: float,
    ) -> None:
        """Heartbeat loop that renews the Redis writer lease periodically."""
        while not stop_event.wait(interval_s):
            try:
                self._ensure_writer_lease(key_id)
            except Exception as exc:
                _logger.warning(
                    "DistributedNonceManager: Redis writer lease heartbeat failed (key=%s err=%s)",
                    key_id,
                    exc,
                )

    def _log_lease_status(
        self,
        key_id: str,
        lease_version: int,
        owner_id: str,
        *,
        force: bool = False,
    ) -> None:
        """Log lease ownership diagnostics with TTL and stability metadata."""
        if _REDIS_LEASE_STATUS_LOG_INTERVAL_S <= 0 and not force:
            return
        now = time.monotonic()
        last_log = self._lease_status_last_log.get(key_id, 0.0)
        if not force and (now - last_log) < _REDIS_LEASE_STATUS_LOG_INTERVAL_S:
            return
        self._lease_status_last_log[key_id] = now
        ttl_ms = -1
        try:
            ttl_ms = int(self._client.pttl(self._LEASE_OWNER_PREFIX + key_id))  # type: ignore[attr-defined]
        except Exception:
            ttl_ms = -1
        stable_for_s = None
        lease_state = self._lease_by_key.get(key_id)
        if lease_state is not None:
            stable_for_s = max(0.0, now - lease_state.stable_since)
        owner_instance = self._owner_instance_id or self._owner_fingerprint
        stable_for_txt = f"{stable_for_s:.1f}s" if isinstance(stable_for_s, float) else "unknown"
        _logger.info(
            "LEASE STATUS: key_id=%s token=%d owner_id=%s owner_instance=%s ttl_remaining_ms=%s stable_for=%s",
            key_id,
            lease_version,
            owner_id,
            owner_instance,
            ttl_ms,
            stable_for_txt,
        )

    def _publish_lock_acquired_state(self, lease_version: int) -> None:
        """Publish lock/fencing runtime state and advance bootstrap FSM when needed."""
        os.environ["NIJA_LOCK_ACQUIRED"] = "true"
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = str(lease_version)
        try:
            bootstrap_state = None
            bootstrap_enum = None
            for module_name in ("bot.bootstrap_state_machine", "bootstrap_state_machine"):
                try:
                    module = importlib.import_module(module_name)
                    bootstrap_state = getattr(module, "get_bootstrap_fsm", lambda: None)()
                    bootstrap_enum = getattr(module, "BootstrapState", None)
                    if bootstrap_state is not None:
                        break
                except Exception:
                    continue
            if bootstrap_state is None:
                return
            current_state = getattr(getattr(bootstrap_state, "state", None), "value", None)
            if current_state is None:
                current_state = getattr(bootstrap_state, "current_state", None)
                current_state = getattr(current_state, "value", current_state)
            if str(current_state) == "BOOT_INIT":
                lock_acquired_state = (
                    getattr(bootstrap_enum, "LOCK_ACQUIRED", None)
                    if bootstrap_enum is not None
                    else "LOCK_ACQUIRED"
                )
                transition = getattr(bootstrap_state, "transition", None)
                if callable(transition):
                    try:
                        transition(lock_acquired_state, reason="redis_writer_lease_acquired")
                    except TypeError:
                        transition(lock_acquired_state, "redis_writer_lease_acquired")
                    _logger.critical(
                        "[BOOTSTRAP FSM] BOOT_INIT -> LOCK_ACQUIRED "
                        "reason=redis_writer_lease_acquired"
                    )
        except Exception as exc:
            _logger.exception(
                "Failed to transition bootstrap FSM after lease acquisition: %s",
                exc,
            )

    def get_writer_lease_status(self, key_id: str) -> dict[str, object]:
        """Return current writer lease status for diagnostics."""
        status: dict[str, object] = {
            "enabled": True,
            "key_id": key_id,
            "token": 0,
            "owner_id": "",
            "owner_instance": self._owner_instance_id or self._owner_fingerprint,
            "ttl_remaining_ms": None,
            "stable_for_s": None,
            "error": "",
        }
        owner_key = self._LEASE_OWNER_PREFIX + key_id
        version_key = self._LEASE_VERSION_PREFIX + key_id
        fingerprint_key = self._LEASE_FINGERPRINT_PREFIX + key_id
        try:
            owner = str(self._client.get(owner_key) or "")  # type: ignore[attr-defined]
            version = int(self._client.get(version_key) or 0)  # type: ignore[attr-defined]
            ttl_ms = int(self._client.pttl(owner_key))  # type: ignore[attr-defined]
            fingerprint = str(self._client.get(fingerprint_key) or "")  # type: ignore[attr-defined]
            status["owner_id"] = owner
            status["token"] = version
            status["ttl_remaining_ms"] = ttl_ms
            status["owner_fingerprint"] = fingerprint
        except Exception as exc:
            status["error"] = str(exc)
            return status
        lease_state = self._lease_by_key.get(key_id)
        if lease_state is not None:
            status["stable_for_s"] = max(0.0, time.monotonic() - lease_state.stable_since)
            status["last_renewed_at"] = lease_state.last_renewed_at
        return status

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
            _emit_nonce_debug_hook(
                "redis_fence_reject",
                key_id=key_id,
                reason=result[1],
                expected_owner=self._owner_id,
                expected_version=lease_version,
                observed_owner=result[3],
                observed_version=result[2],
            )
            raise RuntimeError(
                "Redis fencing check rejected nonce issuance "
                f"(key_id={key_id}, reason={result[1]}, lease_version={result[2]}, owner={result[3]})"
            )
        return int(result[1])

    def get_last(self, key_id: str) -> int:
        """Return the last issued nonce without advancing (0 if never set)."""
        val = self._client.get(self._KEY_PREFIX + key_id)  # type: ignore[attr-defined]
        return int(val) if val else 0

    def reset(self, key_id: str, *, floor_ms: Optional[int] = None) -> None:
        """Re-anchor nonce key to a monotonic floor for *key_id* without deleting it."""
        floor = int(floor_ms) if floor_ms is not None else int(time.time() * 1000) + _REDIS_NONCE_RESET_BUFFER_MS
        self._client.set(self._KEY_PREFIX + key_id, str(floor))  # type: ignore[attr-defined]
        _logger.warning(
            "DistributedNonceManager: Redis nonce key reset for key_id=%s "
            "(floor=%d, buffer_ms=%d)",
            key_id,
            floor,
            _REDIS_NONCE_RESET_BUFFER_MS,
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
        if prev is None:
            self._maybe_apply_startup_backoff(key_id)
        force_enabled = _REDIS_LEASE_FORCE_TAKEOVER and _REDIS_LEASE_FORCE_TAKEOVER_TIMEOUT_S > 0.0

        def _run_lease_script() -> tuple[bool, int, str]:
            _result = self._lease_script(
                keys=[owner_key, version_key, counter_key, fingerprint_key],
                args=[self._owner_id, self._lease_ttl_ms, self._owner_fingerprint],
            )
            _granted = int(_result[0]) == 1
            _lease_version = int(_result[1])
            _current_owner = str(_result[2])
            return _granted, _lease_version, _current_owner

        def _force_takeover() -> tuple[bool, int, str]:
            _result = self._lease_force_script(
                keys=[owner_key, version_key, counter_key, fingerprint_key],
                args=[self._owner_id, self._lease_ttl_ms, self._owner_fingerprint, 1],
            )
            _granted = int(_result[0]) == 1
            _lease_version = int(_result[1])
            _prev_owner = str(_result[2])
            return _granted, _lease_version, _prev_owner

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
                last_refresh_at = wait_started_at
                last_ttl_ms = initial_holder_ttl_ms
                force_attempted = False
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
                    if holder_ttl_ms > last_ttl_ms + _REDIS_LEASE_FORCE_TAKEOVER_REFRESH_DELTA_MS:
                        last_refresh_at = now
                    last_ttl_ms = holder_ttl_ms
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
                    if (
                        force_enabled
                        and not force_attempted
                        and current_owner
                        # Only force takeover if holder_ttl_ms (PTTL in ms) is non-positive (expired/missing).
                        and holder_ttl_ms <= 0
                        and (now - last_refresh_at) >= _REDIS_LEASE_FORCE_TAKEOVER_TIMEOUT_S
                    ):
                        force_attempted = True
                        _logger.critical(
                            "DistributedNonceManager: forcing Redis writer lease takeover "
                            "(key=%s owner=%s lease_version=%d unhealthy_for=%.1fs timeout=%.1fs)",
                            key_id,
                            current_owner,
                            lease_version,
                            max(0.0, now - last_refresh_at),
                            _REDIS_LEASE_FORCE_TAKEOVER_TIMEOUT_S,
                        )
                        granted, lease_version, current_owner = _force_takeover()
                        if granted:
                            self._clear_wait_log_gate(key_id)
                            _logger.critical(
                                "DistributedNonceManager: Redis writer lease force-acquired "
                                "(key=%s lease_version=%d prev_owner=%s)",
                                key_id,
                                lease_version,
                                current_owner or "<unknown>",
                            )
                            break
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
        now = time.monotonic()
        if prev is None:
            self._lease_by_key[key_id] = self._LeaseState(
                version=lease_version,
                owner_id=self._owner_id,
                stable_since=now,
                last_renewed_at=now,
            )
            self._ensure_lease_heartbeat(key_id)
            self._log_lease_status(key_id, lease_version, current_owner, force=True)
            _logger.info(
                "DistributedNonceManager: Redis writer lease acquired key=%s lease_version=%d owner=%s",
                key_id,
                lease_version,
                self._owner_fingerprint,
            )
            self._publish_lock_acquired_state(lease_version)
            return lease_version

        # Fencing rule: once a process has a lease version, any version rotation
        # means lease continuity was lost (TTL expiry / partition / failover).
        if prev.version != lease_version:
            # Same-owner version changes can happen during Redis failover/reload or metadata refresh
            # during renewals; avoid self-fencing and preserve stable_since continuity.
            if current_owner == self._owner_id:
                _logger.warning(
                    "DistributedNonceManager: same-owner lease version change; preserving continuity "
                    "(key=%s prev=%d new=%d)",
                    key_id,
                    prev.version,
                    lease_version,
                )
                self._lease_by_key[key_id] = self._LeaseState(
                    version=lease_version,
                    owner_id=self._owner_id,
                    stable_since=prev.stable_since,
                    last_renewed_at=now,
                )
                self._log_lease_status(key_id, lease_version, current_owner, force=True)
                return lease_version
            if lease_version < prev.version:
                reset_msg = (
                    "Redis reset detected: writer lease version decreased "
                    f"(key_id={key_id}, prev={prev.version}, new={lease_version})."
                )
                if self._strict_lease:
                    policy = os.environ.get("NIJA_REDIS_RESET_POLICY", "require_confirmation").strip().lower()
                    ack = _env_true("NIJA_REDIS_RESET_ACK", "0")
                    reconciled = _env_true("NIJA_REDIS_RESET_RECONCILED", "0")
                    if policy not in {"auto_reinit", "require_confirmation"}:
                        policy = "require_confirmation"
                    if policy == "auto_reinit" and not reconciled:
                        raise RuntimeError(
                            f"{reset_msg} Auto-reinit requires reconciliation. "
                            "Set NIJA_REDIS_RESET_RECONCILED=true after exchange state is verified."
                        )
                    if policy != "auto_reinit" and not ack:
                        raise RuntimeError(
                            f"{reset_msg} Set NIJA_REDIS_RESET_ACK=true to proceed after verifying persistence."
                        )
                    _logger.critical("%s Recovery acknowledged; continuing.", reset_msg)
                else:
                    _logger.critical(reset_msg)
                self._lease_by_key[key_id] = self._LeaseState(
                    version=lease_version,
                    owner_id=self._owner_id,
                    stable_since=now,
                    last_renewed_at=now,
                )
                self._log_lease_status(key_id, lease_version, current_owner, force=True)
                return lease_version
            msg = (
                "Redis writer lease fencing token changed "
                f"(key_id={key_id}, prev={prev.version}, new={lease_version}). "
                "Hard-stopping to prevent split-brain writes."
            )
            if self._strict_lease:
                raise RuntimeError(msg)
            _logger.critical(msg)
            self._lease_by_key[key_id] = self._LeaseState(
                version=lease_version,
                owner_id=self._owner_id,
                stable_since=now,
                last_renewed_at=now,
            )
            self._log_lease_status(key_id, lease_version, current_owner, force=True)
            return lease_version
        self._lease_by_key[key_id] = self._LeaseState(
            version=lease_version,
            owner_id=self._owner_id,
            stable_since=prev.stable_since,
            last_renewed_at=now,
        )
        self._log_lease_status(key_id, lease_version, current_owner)
        return lease_version

    def ensure_writer_lease(self, key_id: str) -> int:
        """Public wrapper around lease acquire/renew + fencing validation."""
        return self._ensure_writer_lease(key_id)

    def release_writer_lease(self, key_id: str) -> bool:
        """Release the Redis writer lease for *key_id* if still owned by this process."""
        owner_key = self._LEASE_OWNER_PREFIX + key_id
        version_key = self._LEASE_VERSION_PREFIX + key_id
        fingerprint_key = self._LEASE_FINGERPRINT_PREFIX + key_id
        try:
            released = int(
                self._lease_release_script(  # type: ignore[call-arg]
                    keys=[owner_key, version_key, fingerprint_key],
                    args=[self._owner_id],
                )
            )
            if released:
                self._lease_by_key.pop(key_id, None)
                self._stop_lease_heartbeat(key_id)
            return bool(released)
        except Exception:
            return False


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
        self._owner_instance_id = _resolve_instance_id()
        self._strict_redis_lease = _runtime_strict_redis_lease()

        if redis_client is None:
            if _live_mode_active():
                raise RuntimeError(
                    "DistributedNonceManager: Redis nonce backend is required in LIVE mode; "
                    "refusing file/fcntl fallback"
                )
            _logger.critical(
                "DistributedNonceManager: redis_client is None — "
                "falling back to file-based per-key locks (single-host safe). "
                "⚠️  Multi-instance coordination is DISABLED. "
                "This is a TEMPORARY fallback while Redis TLS is being fixed."
            )
            return

        try:
            self._redis = _PerKeyRedisBackend(
                redis_client=redis_client,
                owner_id=self._owner_id,
                owner_fingerprint=self._owner_fingerprint,
                owner_instance_id=self._owner_instance_id,
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
            if _live_mode_active():
                raise RuntimeError(
                    "DistributedNonceManager: Redis backend unavailable in LIVE mode; "
                    "refusing file/fcntl fallback"
                ) from exc
            _logger.critical(
                "DistributedNonceManager: Redis backend unavailable (%s). "
                "⚠️  Falling back to file-based per-key locks — "
                "multi-instance coordination is DISABLED. "
                "This is a TEMPORARY fallback while Redis TLS is being fixed.",
                exc,
            )
            # File-lock fallback: self._redis remains None; get_nonce() will
            # route through _file_nonce() instead.

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
        api_key_id = _require_api_key_id(api_key_id)
        trace_id = f"{int(time.time() * 1000)}-{threading.get_ident()}"
        _emit_nonce_debug_hook(
            "nonce_request_start",
            trace_id=trace_id,
            key_id=api_key_id,
            backend=("redis" if self._redis is not None else "file"),
        )
        # Hard gate: fail immediately if the FSM has revoked nonce issuance.
        if not _get_nonce_auth():
            _emit_nonce_debug_hook(
                "nonce_request_blocked",
                trace_id=trace_id,
                key_id=api_key_id,
                reason="fsm_unauthorized",
            )
            raise RuntimeError(
                f"DistributedNonceManager.get_nonce: nonce issuance not authorized "
                f"(key={api_key_id}) — startup FSM is in FAILED/IDLE state; "
                "wait for NONCE_READY / CONNECTED before issuing nonces"
            )
        if self._redis is None:
            if _live_mode_active():
                raise RuntimeError(
                    "DistributedNonceManager.get_nonce: Redis nonce backend unavailable in LIVE mode; "
                    "refusing file/fcntl fallback"
                )
            # TEMPORARY degraded mode: Redis is unavailable; fall back to
            # file-based per-key fcntl locks (single-host safe).
            # ⚠️  Multi-instance coordination is DISABLED in this path.
            _logger.critical(
                "DistributedNonceManager.get_nonce: Redis unavailable — "
                "issuing nonce via file-lock fallback for key=%s. "
                "⚠️  Multi-instance coordination is DISABLED. "
                "This is a TEMPORARY fallback while Redis TLS is being fixed.",
                api_key_id,
            )
            nonce = self._file_nonce(api_key_id)
            _emit_nonce_debug_hook(
                "nonce_request_success",
                trace_id=trace_id,
                key_id=api_key_id,
                nonce=nonce,
                backend="file",
            )
            return nonce
        try:
            nonce = self._redis.next_nonce(api_key_id)
            _emit_nonce_debug_hook(
                "nonce_request_success",
                trace_id=trace_id,
                key_id=api_key_id,
                nonce=nonce,
                backend="redis",
            )
            return nonce
        except Exception as exc:
            _emit_nonce_debug_hook(
                "nonce_request_redis_failure",
                trace_id=trace_id,
                key_id=api_key_id,
                error=exc,
            )
            # Redis is the single writer authority. When Redis was configured
            # and connected, a runtime failure must never silently fall back to
            # the file-lock path. The file-based KrakenNonceManager counter has
            # NOT been advanced by Redis-issued nonces, so any value it produces
            # is far below Kraken's recorded high-water mark and will be
            # immediately rejected — a stale nonce is worse than no nonce.
            # Raise unconditionally so the caller can reconnect and retry.
            raise RuntimeError(
                f"DistributedNonceManager.get_nonce: Redis nonce issuance failed "
                f"for key={api_key_id} ({exc}) — refusing file/fcntl fallback to "
                "preserve single-writer Redis authority; caller should reconnect Redis and retry"
            ) from exc

    def record_error(self, api_key_id: str) -> None:
        """Record a nonce rejection from Kraken for *api_key_id*.

        In Redis mode, nonce recovery is handled entirely by the Redis monotonic
        counter (the next ``get_nonce()`` call will produce a higher value).
        The file-based KrakenNonceManager is NOT consulted: its counter has not
        been driven by Redis-issued nonces, so forwarding errors to it would
        trigger stale-state escalation (nuclear resets, probe loops) against a
        counter value that has nothing to do with the current session.

        In file mode this directly calls ``record_error()`` on the per-key manager.
        """
        api_key_id = _require_api_key_id(api_key_id)
        _emit_nonce_debug_hook("nonce_record_error", key_id=api_key_id)
        if self._redis is not None:
            # Redis is the authority; skip file-based state machine to prevent
            # spurious escalation from a stale counter.
            _logger.debug(
                "DistributedNonceManager.record_error: key=%s "
                "(Redis mode — file-manager state skipped)",
                api_key_id,
            )
            return
        try:
            mgr = self._get_file_manager(api_key_id)
            mgr.record_error()
        except Exception as exc:
            _logger.debug(
                "DistributedNonceManager.record_error: key=%s error=%s",
                api_key_id, exc,
            )

    def record_success(self, api_key_id: str, nonce: int) -> None:
        """Record that Kraken accepted *nonce* for *api_key_id*.

        In Redis mode, success tracking is handled by the Redis counter.
        The file-based KrakenNonceManager is NOT consulted: its
        ``_last_successful_nonce`` would be set from a stale file counter, not
        from the Redis-issued value, creating a divergent success-history record
        that could mislead the pre-request monotonicity guard.

        In file mode this directly calls ``record_success()`` on the per-key manager.
        """
        api_key_id = _require_api_key_id(api_key_id)
        _emit_nonce_debug_hook("nonce_record_success", key_id=api_key_id, nonce=nonce)
        if self._redis is not None:
            # Redis is the authority; skip file-based state to avoid divergence.
            _logger.debug(
                "DistributedNonceManager.record_success: key=%s nonce=%d "
                "(Redis mode — file-manager state skipped)",
                api_key_id, nonce,
            )
            return
        try:
            mgr = self._get_file_manager(api_key_id)
            mgr.record_success()
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
        api_key_id = _require_api_key_id(api_key_id)
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

    def probe_server_sync(self, api_key_id: str) -> None:
        """Reset the nonce for *api_key_id* to a server-time floor before a probe.

        The startup probe handshake calls ``_probe_mgr.probe_and_resync()`` which
        invokes ``server_sync_resync()`` on the file-backed ``KrakenNonceManager``.
        However the actual probe API call uses ``get_nonce(api_key_id)`` which in
        Redis mode reads from a *separate* Redis counter — one that
        ``server_sync_resync`` never touches.  If the Redis counter was advanced
        by prior nuclear resets or repeated failed probe attempts it will remain
        stale-high and Kraken will keep rejecting the probe nonces even after a
        ``NIJA_FORCE_NONCE_RESYNC=1`` restart.

        Calling this method immediately before ``probe_and_resync()`` closes the
        gap:

        * **Redis mode** — re-anchors the per-key Redis nonce entry to
          ``now_ms + NIJA_REDIS_NONCE_RESET_BUFFER_MS`` so the next
          ``get_nonce()`` call preserves monotonicity while escaping poisoned
          high-water marks.

        * **File mode** — the per-key ``KrakenNonceManager`` and the
          ``DistributedNonceManager`` file path are the same object, so
          ``server_sync_resync`` inside ``probe_and_resync`` already advances the
          right counter.  This method is a deliberate no-op in that path.
        """
        api_key_id = _require_api_key_id(api_key_id)
        if self._redis is not None:
            try:
                self._redis.reset(api_key_id)
                _logger.info(
                    "DistributedNonceManager.probe_server_sync: Redis nonce reset "
                    "for key=%s — probe will use a fresh monotonic floor",
                    api_key_id,
                )
            except Exception as exc:
                _logger.warning(
                    "DistributedNonceManager.probe_server_sync: Redis reset failed "
                    "for key=%s (%s) — probe may use a stale Redis nonce",
                    api_key_id,
                    exc,
                )
        # File mode: probe_and_resync's internal server_sync_resync already
        # targets the correct counter; nothing extra needed here.

    def get_last_nonce(self, api_key_id: str) -> int:
        """Return the last issued nonce without advancing it (diagnostic use)."""
        api_key_id = _require_api_key_id(api_key_id)
        if self._redis is not None:
            try:
                return self._redis.get_last(api_key_id)
            except Exception:
                return 0
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
        api_key_id = _require_api_key_id(api_key_id)
        if self._redis is None:
            return
        lease_version = self._redis.ensure_writer_lease(api_key_id)
        setattr(self, "lease_version", lease_version)

    def release_writer_lease(self, api_key_id: str) -> bool:
        """Release the Redis writer lease for *api_key_id* if held by this process."""
        api_key_id = _require_api_key_id(api_key_id)
        if self._redis is None:
            return False
        return self._redis.release_writer_lease(api_key_id)

    def get_writer_lease_status(self, api_key_id: str) -> dict[str, object]:
        """Return writer lease diagnostics for *api_key_id* (never raises)."""
        api_key_id = _require_api_key_id(api_key_id)
        if self._redis is None:
            return {"enabled": False, "key_id": api_key_id, "error": "redis_unavailable"}
        try:
            return self._redis.get_writer_lease_status(api_key_id)
        except Exception as exc:
            return {"enabled": True, "key_id": api_key_id, "error": str(exc)}

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
        if self._redis is not None:
            try:
                self._redis.ensure_writer_lease(api_key_id)
                return True
            except Exception:
                return False
        try:
            return bool(self._get_file_manager(api_key_id).can_issue_nonce())
        except Exception:
            return False

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _file_nonce(self, api_key_id: str) -> int:
        """Issue next nonce via the per-key KrakenNonceManager (file/fcntl)."""
        api_key_id = _require_api_key_id(api_key_id)
        return self._get_file_manager(api_key_id).next_nonce()

    def _get_file_manager(self, api_key_id: str):
        """Return the per-key KrakenNonceManager, creating it if needed."""
        api_key_id = _require_api_key_id(api_key_id)
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
        # Auto-construct Redis client from env if not supplied.
        if redis_client is None:
            redis_url = get_redis_url()
            if not redis_url:
                if _live_mode_active():
                    raise RuntimeError(
                        "DistributedNonceManager: NIJA_REDIS_URL is required in LIVE mode; "
                        "refusing file/fcntl fallback"
                    )
                # TEMPORARY degraded mode: no Redis URL configured.
                # Fall back to file-based per-key locks if degraded mode is active.
                _logger.critical(
                    "DistributedNonceManager: NIJA_REDIS_URL is not configured — "
                    "falling back to file-based per-key locks (single-host safe). "
                    "⚠️  Multi-instance coordination is DISABLED. "
                    "This is a TEMPORARY fallback while Redis TLS is being fixed."
                )
                _dnm_instance = DistributedNonceManager(redis_client=None)
                return _dnm_instance
            try:
                redis_client, used_url = connect_redis_with_fallback(
                    url=redis_url,
                    decode_responses=True,
                    socket_timeout=2,
                    socket_connect_timeout=2,
                    retries=1,
                    delay_s=0.0,
                    max_total_wait_s=3.0,
                    log=lambda msg: _logger.debug("DistributedNonceManager redis connect: %s", msg),
                )
                _logger.info(
                    "DistributedNonceManager: auto-connecting to Redis at %s",
                    _redact_redis_url(used_url),
                )
            except Exception as exc:
                if _live_mode_active():
                    raise RuntimeError(
                        "DistributedNonceManager: could not connect Redis nonce backend in LIVE mode; "
                        "refusing file/fcntl fallback"
                    ) from exc
                # TEMPORARY degraded mode: Redis connection failed.
                # Fall back to file-based per-key locks rather than crashing.
                _logger.critical(
                    "DistributedNonceManager: could not connect to Redis at %s (%s) — "
                    "falling back to file-based per-key locks (single-host safe). "
                    "⚠️  Multi-instance coordination is DISABLED. "
                    "This is a TEMPORARY fallback while Redis TLS is being fixed.",
                    _redact_redis_url(redis_url),
                    exc,
                )
                _dnm_instance = DistributedNonceManager(redis_client=None)
                return _dnm_instance
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
