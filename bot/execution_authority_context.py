"""
Execution authority context
===========================

Provides a thread/task-safe context marker used to assert that broker order
submission is happening through the canonical ExecutionPipeline path.
"""

from __future__ import annotations

import os
import threading
import time
import logging
import importlib
from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from bot.instance_identity import (
    current_instance_identity,
    inspect_lock_holder,
    parse_distributed_lock_holder,
    parse_writer_lock_metadata,
)
from bot.redis_env import get_redis_url

try:
    from bot.single_execution_authority_kernel import get_seak
except ImportError:
    try:
        from single_execution_authority_kernel import get_seak  # type: ignore[import]
    except ImportError:
        get_seak = None  # type: ignore[assignment]


_EXECUTION_AUTHORITY_ACTIVE: ContextVar[bool] = ContextVar(
    "nija_execution_authority_active",
    default=False,
)

_FENCE_VERIFY_LOCK = threading.Lock()
_FENCE_LAST_CHECK_TS: float = 0.0
_FENCE_LAST_OK: bool = False
_FENCE_LAST_ERR: str = ""
_FENCE_RECOVER_NEXT_ATTEMPT_TS: float = 0.0

logger = logging.getLogger("nija.execution_authority")


@dataclass(frozen=True)
class RuntimeAuthoritySnapshot:
    ready: bool
    authority_ready: bool
    nonce_ready: bool
    dispatch_health_ready: bool
    dispatch_enabled: bool
    kill_switch_active: bool
    coordinator_state: str


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "enabled", "on"}


def _single_instance_lock_opt_out(live_mode: bool) -> bool:
    """True when operator explicitly allows single-instance live mode without strict lock."""
    if not live_mode:
        return False
    if _env_truthy("NIJA_MULTI_INSTANCE_POSSIBLE"):
        return False
    if not _env_truthy("NIJA_ASSUME_SINGLE_INSTANCE"):
        return False
    if _env_truthy("NIJA_REQUIRE_DISTRIBUTED_LOCK"):
        return False
    if _env_truthy("STRICT_REDIS_WRITER_LOCK"):
        return False
    return True


def _build_redis_client(redis_mod, redis_url: str, *, timeout_s: int = 2):
    """Create a Redis client with Railway-compatible TLS behavior."""
    kwargs = {
        "decode_responses": True,
        "socket_connect_timeout": timeout_s,
        "socket_timeout": timeout_s,
    }
    try:
        try:
            from bot.redis_runtime import get_redis_tls_kwargs
        except ImportError:
            from redis_runtime import get_redis_tls_kwargs  # type: ignore[import]
        kwargs.update(get_redis_tls_kwargs(redis_url))
    except Exception as exc:
        logger.debug("authority redis tls kwargs unavailable; continuing with defaults: %s", exc)
    return redis_mod.Redis.from_url(redis_url, **kwargs)


def _connect_redis_for_authority(redis_url: str, *, timeout_s: int = 2):
    """Build Redis client with startup fallback logic where available."""
    redis_mod = importlib.import_module("redis")
    try:
        try:
            from bot.redis_runtime import connect_redis_with_fallback
        except ImportError:
            from redis_runtime import connect_redis_with_fallback  # type: ignore[import]
        client, _ = connect_redis_with_fallback(
            url=redis_url,
            decode_responses=True,
            socket_timeout=timeout_s,
            socket_connect_timeout=timeout_s,
            retries=1,
            delay_s=0.0,
            log=lambda msg: logger.debug("authority redis connect fallback: %s", msg),
        )
        return client
    except Exception:
        return _build_redis_client(redis_mod, redis_url, timeout_s=timeout_s)


def _recover_fencing_token_from_lock(redis_url: str, lock_key: str) -> str:
    """Recover fencing token from Redis lock when holder is this instance."""
    global _FENCE_RECOVER_NEXT_ATTEMPT_TS

    if not redis_url or not lock_key:
        return ""

    try:
        recover_cooldown_s = max(
            1.0,
            float(os.getenv("NIJA_WRITER_TOKEN_RECOVERY_COOLDOWN_S", "30") or 30.0),
        )
    except (TypeError, ValueError):
        recover_cooldown_s = 30.0

    now = time.monotonic()
    with _FENCE_VERIFY_LOCK:
        if now < _FENCE_RECOVER_NEXT_ATTEMPT_TS:
            return ""

    try:
        client = _connect_redis_for_authority(redis_url, timeout_s=2)
        current_holder_raw = str(client.get(lock_key) or "")
        current_holder = parse_distributed_lock_holder(current_holder_raw)
        inspection = inspect_lock_holder(current_instance_identity(), current_holder)
        relationship = str(inspection.get("relationship", ""))
        if relationship not in {"same-instance", "same-replica"}:
            with _FENCE_VERIFY_LOCK:
                _FENCE_RECOVER_NEXT_ATTEMPT_TS = time.monotonic() + recover_cooldown_s
            return ""
        token = str(current_holder.get("token", "") or "").strip()
        if not token:
            with _FENCE_VERIFY_LOCK:
                _FENCE_RECOVER_NEXT_ATTEMPT_TS = time.monotonic() + recover_cooldown_s
            return ""
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = token
        with _FENCE_VERIFY_LOCK:
            _FENCE_RECOVER_NEXT_ATTEMPT_TS = 0.0
        logger.warning(
            "Recovered NIJA_WRITER_FENCING_TOKEN from Redis lock holder "
            "(relationship=%s lock_key=%s token_prefix=%s)",
            relationship,
            lock_key,
            token[:8],
        )
        return token
    except Exception as exc:
        with _FENCE_VERIFY_LOCK:
            _FENCE_RECOVER_NEXT_ATTEMPT_TS = time.monotonic() + recover_cooldown_s
        live_mode = _env_truthy("LIVE_CAPITAL_VERIFIED")
        if _single_instance_lock_opt_out(live_mode):
            logger.info("Unable to recover fencing token from Redis lock (degraded/opt-out): %s", exc)
        else:
            logger.warning("Unable to recover fencing token from Redis lock: %s", exc)
        return ""


def assert_distributed_writer_authority() -> None:
    """Fail closed when this process no longer owns the distributed writer lock.

    Validation source:
    - ``NIJA_WRITER_FENCING_TOKEN`` (set at startup when lock acquired)
    - ``NIJA_WRITER_LOCK_KEY`` (or scoped default)
    - Redis value at lock key must begin with the same token

    Runtime cost is bounded by a short verification cache to avoid a Redis
    round-trip on every order.

    SAFETY CONTRACT
    ---------------
    This function ALWAYS enforces strict distributed fencing.  There are no
    degraded-mode bypasses, no single-instance opt-outs, and no fail-open
    paths.  If Redis is unreachable or the fencing token is missing or
    mismatched, a RuntimeError is raised unconditionally.
    """
    global _FENCE_LAST_CHECK_TS, _FENCE_LAST_OK, _FENCE_LAST_ERR

    import hashlib

    redis_url = get_redis_url()
    scope = os.getenv("NIJA_WRITER_LOCK_SCOPE", "").strip()
    if not scope:
        raw = (
            os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
            or os.environ.get("KRAKEN_API_KEY", "").strip()
            or "default"
        )
        scope = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    lock_key = os.getenv("NIJA_WRITER_LOCK_KEY", "").strip() or f"nija:writer_lock:{scope}"

    # Fencing token is mandatory — no recovery fallback permitted.
    token = os.getenv("NIJA_WRITER_FENCING_TOKEN", "").strip()
    if not token:
        _err = (
            "LIVE TRADING BLOCKED: NIJA_WRITER_FENCING_TOKEN is not set. "
            "Distributed writer authority requires a valid fencing token. "
            "Ensure the bot acquired a Redis writer lease at startup."
        )
        with _FENCE_VERIFY_LOCK:
            _FENCE_LAST_CHECK_TS = time.monotonic()
            _FENCE_LAST_OK = False
            _FENCE_LAST_ERR = _err
        raise RuntimeError(_err)

    # Redis URL is mandatory — no local fallback permitted.
    if not redis_url:
        _err = (
            "LIVE TRADING BLOCKED: Redis URL is not configured. "
            "Distributed writer authority requires Redis connectivity. "
            "Set NIJA_REDIS_URL to a valid rediss:// endpoint."
        )
        with _FENCE_VERIFY_LOCK:
            _FENCE_LAST_CHECK_TS = time.monotonic()
            _FENCE_LAST_OK = False
            _FENCE_LAST_ERR = _err
        raise RuntimeError(_err)

    try:
        verify_ttl_s = max(0.0, float(os.getenv("NIJA_WRITER_RUNTIME_VERIFY_TTL_S", "1.5") or 1.5))
    except (TypeError, ValueError):
        verify_ttl_s = 1.5
        logger.warning(
            "Invalid NIJA_WRITER_RUNTIME_VERIFY_TTL_S value; using default %.1fs",
            verify_ttl_s,
        )
    now = time.monotonic()
    with _FENCE_VERIFY_LOCK:
        if verify_ttl_s > 0 and (now - _FENCE_LAST_CHECK_TS) <= verify_ttl_s:
            if _FENCE_LAST_OK:
                return
            raise RuntimeError(_FENCE_LAST_ERR or "distributed writer fence verification cached failure")

    try:
        client = _connect_redis_for_authority(redis_url, timeout_s=2)
        current = client.get(lock_key)
        current_token = ""
        if isinstance(current, str) and current:
            current_token = current.split(":", 1)[0]

        ok = (current_token == token)
        err = ""
        if not ok:
            err = (
                "distributed writer fencing mismatch: "
                f"expected_token={token} current_token={current_token or '<missing>'}"
            )

        with _FENCE_VERIFY_LOCK:
            _FENCE_LAST_CHECK_TS = time.monotonic()
            _FENCE_LAST_OK = ok
            _FENCE_LAST_ERR = err

        if not ok:
            raise RuntimeError(err)

    except RuntimeError:
        raise
    except Exception as exc:
        _err = f"LIVE TRADING BLOCKED: Redis execution authority unavailable — {exc}"
        with _FENCE_VERIFY_LOCK:
            _FENCE_LAST_CHECK_TS = time.monotonic()
            _FENCE_LAST_OK = False
            _FENCE_LAST_ERR = _err
        raise RuntimeError(_err) from exc


def get_distributed_writer_authority_status(force_refresh: bool = False) -> dict:
    """Return current distributed-writer ownership status for diagnostics.

    This helper never raises; it is safe to call from health/status endpoints.
    """
    global _FENCE_LAST_CHECK_TS

    live_mode = _env_truthy("LIVE_CAPITAL_VERIFIED")
    unsafe_bypass = False
    single_instance_opt_out = _single_instance_lock_opt_out(live_mode)
    strict_required = (
        _env_truthy("NIJA_REQUIRE_DISTRIBUTED_LOCK")
        or _env_truthy("STRICT_REDIS_WRITER_LOCK")
        or (live_mode and not single_instance_opt_out)
    )
    effective_strict_required = strict_required
    redis_url = get_redis_url()
    token = os.getenv("NIJA_WRITER_FENCING_TOKEN", "").strip()
    scope = os.getenv("NIJA_WRITER_LOCK_SCOPE", "").strip()
    if not scope:
        raw = (
            os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
            or os.environ.get("KRAKEN_API_KEY", "").strip()
            or "default"
        )
        import hashlib
        scope = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    lock_key = os.getenv("NIJA_WRITER_LOCK_KEY", "").strip() or f"nija:writer_lock:{scope}"
    meta_key = os.getenv("NIJA_WRITER_LOCK_META_KEY", "").strip() or f"nija:writer_lock_meta:{scope}"

    if not token and redis_url:
        token = _recover_fencing_token_from_lock(redis_url, lock_key)

    if force_refresh:
        with _FENCE_VERIFY_LOCK:
            _FENCE_LAST_CHECK_TS = 0.0

    ok = True
    err = ""
    try:
        assert_distributed_writer_authority()
    except Exception as exc:
        ok = False
        err = str(exc)

    with _FENCE_VERIFY_LOCK:
        last_check_ts = _FENCE_LAST_CHECK_TS
        last_ok = _FENCE_LAST_OK
        last_err = _FENCE_LAST_ERR

    current_holder_raw = ""
    current_holder = parse_distributed_lock_holder("")
    current_holder_meta = parse_writer_lock_metadata("")
    current_instance = current_instance_identity()
    holder_inspection = inspect_lock_holder(current_instance, current_holder)
    redis_reachable = False
    if redis_url:
        try:
            client = _connect_redis_for_authority(redis_url, timeout_s=2)
            redis_reachable = bool(client.ping())
            current_holder_raw = str(client.get(lock_key) or "")
            current_holder_meta = parse_writer_lock_metadata(str(client.get(meta_key) or ""))
            current_holder = parse_distributed_lock_holder(current_holder_raw)
            holder_inspection = inspect_lock_holder(current_instance, current_holder)
        except Exception as exc:
            current_holder = {
                "raw": current_holder_raw,
                "display": "<unavailable>",
                "error": str(exc),
            }
            current_holder_meta = {
                "raw": "",
                "display": "<unavailable>",
                "error": str(exc),
            }
            holder_inspection = inspect_lock_holder(current_instance, current_holder)

    return {
        "ok": bool(ok),
        "error": err,
        "strict_required": bool(strict_required),
        "effective_strict_required": bool(effective_strict_required),
        "degraded_override_enabled": False,
        "unsafe_bypass_enabled": bool(unsafe_bypass),
        "single_instance_lock_opt_out": bool(single_instance_opt_out),
        "live_mode": bool(live_mode),
        "redis_configured": bool(redis_url),
        "redis_reachable": bool(redis_reachable),
        "token_present": bool(token),
        "token_prefix": token[:8] if token else "",
        "lock_key": lock_key,
        "meta_key": meta_key,
        "current_instance": current_instance,
        "current_holder": current_holder,
        "current_holder_meta": current_holder_meta,
        "holder_inspection": holder_inspection,
        "cache": {
            "last_check_monotonic": float(last_check_ts),
            "last_ok": bool(last_ok),
            "last_error": last_err,
        },
    }


def get_startup_execution_authority_prerequisites(force_refresh: bool = False) -> dict:
    """Return startup authority prerequisites required before live runtime handoff."""
    authority = get_distributed_writer_authority_status(force_refresh=force_refresh)
    lease_acquired = _env_truthy("NIJA_WRITER_LEASE_ACQUIRED")
    heartbeat_flag = _env_truthy("NIJA_WRITER_HEARTBEAT_ACTIVE")
    token = os.getenv("NIJA_WRITER_FENCING_TOKEN", "").strip()

    try:
        heartbeat_last_ts = float(os.getenv("NIJA_WRITER_HEARTBEAT_LAST_TS", "0") or 0.0)
    except (TypeError, ValueError):
        heartbeat_last_ts = 0.0

    try:
        ttl_s = float(os.getenv("NIJA_WRITER_LOCK_TTL_S", "0") or 0.0)
    except (TypeError, ValueError):
        ttl_s = 0.0

    heartbeat_max_age_s = max(ttl_s * 2.0, 30.0)
    heartbeat_fresh = heartbeat_last_ts > 0 and (time.time() - heartbeat_last_ts) <= heartbeat_max_age_s
    heartbeat_active = heartbeat_flag and heartbeat_fresh

    checks = {
        "redis_reachable": bool(authority.get("redis_reachable", False)),
        "lease_acquired": bool(lease_acquired),
        "fencing_token_active": bool(token) and bool(authority.get("token_present", False)),
        "heartbeat_active": bool(heartbeat_active),
        "authority_verified": bool(authority.get("ok", False)),
    }
    missing = [name for name, ok in checks.items() if not ok]

    return {
        "ready": not missing,
        "checks": checks,
        "missing": missing,
        "heartbeat_last_ts": heartbeat_last_ts,
        "heartbeat_max_age_s": heartbeat_max_age_s,
        "authority_status": authority,
    }


def require_startup_execution_authority(*, context: str, force_refresh: bool = False) -> dict:
    """Raise when startup execution authority prerequisites are not fully satisfied."""
    status = get_startup_execution_authority_prerequisites(force_refresh=force_refresh)
    if status["ready"]:
        return status

    checks = status["checks"]
    missing = ", ".join(status["missing"]) or "unknown"
    authority_error = str(status["authority_status"].get("error") or "")
    raise RuntimeError(
        "STARTUP_EXECUTION_AUTHORITY_REQUIRED: "
        f"context={context} missing={missing} "
        f"checks={checks} authority_error={authority_error or '<none>'}"
    )


@contextmanager
def execution_authority_scope() -> Iterator[None]:
    """Mark the current context as execution-authorized for broker submits."""
    token = _EXECUTION_AUTHORITY_ACTIVE.set(True)
    try:
        yield
    finally:
        _EXECUTION_AUTHORITY_ACTIVE.reset(token)


def has_execution_authority() -> bool:
    """Return True when the current context is authorized for order submit."""
    return bool(_EXECUTION_AUTHORITY_ACTIVE.get())


def is_seak_halted() -> bool:
    """Return True when the global execution kernel is halted."""
    if get_seak is None:
        return False
    try:
        return bool(getattr(get_seak(), "is_halted", False))
    except Exception as exc:
        logger.warning("SEAK halt status unavailable; failing closed: %s", exc)
        return True


def assert_startup_write_authority() -> None:
    """Fail closed unless startup write-capable authority is fully available."""
    assert_distributed_writer_authority()

    if not has_execution_authority():
        raise RuntimeError("Startup execution authority unavailable")

    if is_seak_halted():
        raise RuntimeError("SEAK halt active")


def assert_execution_dispatch_permitted() -> None:
    """Fail closed unless writer authority and execution scope are both valid."""
    assert_distributed_writer_authority()
    if not has_execution_authority():
        raise RuntimeError(
            "Execution authority violation: order submission must originate from ExecutionPipeline"
        )


def runtime_authority_snapshot() -> RuntimeAuthoritySnapshot:
    """Return runtime convergence status for dispatch-time authority checks."""
    try:
        try:
            from bot.startup_coordinator import get_startup_coordinator
        except ImportError:
            from startup_coordinator import get_startup_coordinator  # type: ignore[import]

        coordinator = get_startup_coordinator()
        snapshot = coordinator.build_snapshot(
            trading_state=os.getenv("NIJA_RUNTIME_TRADING_STATE", ""),
            activation_intent=_env_truthy("LIVE_CAPITAL_VERIFIED")
            or _env_truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY"),
        )
        ready = bool(
            snapshot.authority_ready
            and snapshot.nonce_ready
            and snapshot.dispatch_health_ready
            and snapshot.dispatch_enabled
            and not snapshot.kill_switch_active
        )
        return RuntimeAuthoritySnapshot(
            ready=ready,
            authority_ready=bool(snapshot.authority_ready),
            nonce_ready=bool(snapshot.nonce_ready),
            dispatch_health_ready=bool(snapshot.dispatch_health_ready),
            dispatch_enabled=bool(snapshot.dispatch_enabled),
            kill_switch_active=bool(snapshot.kill_switch_active),
            coordinator_state=str(snapshot.coordinator_state),
        )
    except Exception as exc:
        logger.warning("Runtime authority snapshot unavailable; failing closed: %s", exc)
        return RuntimeAuthoritySnapshot(
            ready=False,
            authority_ready=False,
            nonce_ready=False,
            dispatch_health_ready=False,
            dispatch_enabled=False,
            kill_switch_active=False,
            coordinator_state="unavailable",
        )
