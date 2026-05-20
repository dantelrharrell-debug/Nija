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
    runtime_state: str
    reason: str


@dataclass(frozen=True)
class ExecutionDecision:
    allowed: bool
    reason: str
    circuit_state: str
    state_live_active: bool
    lease_valid: bool
    lease_generation_current: bool
    heartbeat_fresh: bool
    heartbeat_stage_sufficient: bool
    broker_health_ok: bool
    circuit_breaker_closed: bool
    dispatch_enabled: bool
    stability_allowed: bool
    stability_halt_state: str
    stability_throttle: float
    stability_size_multiplier: float
    stability_stress_score: float
    stability_collapsed_risk_score: float
    stability_reason: str


@dataclass(frozen=True)
class StabilityAuthoritySnapshot:
    allowed: bool
    halt_state: str
    throttle: float
    size_multiplier: float
    stress_score: float
    collapsed_risk_score: float
    reason: str


class ExecutionBlocked(RuntimeError):
    """Raised when canonical execution gate denies order dispatch."""


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "enabled", "on"}


def _read_current_lease_generation() -> tuple[int, str]:
    """Read monotonic lease generation from Redis."""
    redis_url = get_redis_url()
    if not redis_url:
        return 0, "redis_unavailable"
    generation_key = os.getenv("NIJA_LEASE_GENERATION_KEY", "nija:lease:generation").strip() or "nija:lease:generation"
    try:
        client = _connect_redis_for_authority(redis_url, timeout_s=2)
        raw_generation = client.get(generation_key)  # type: ignore[attr-defined]
        if raw_generation is None:
            return 0, "generation_missing"
        return int(str(raw_generation).strip()), ""
    except Exception as exc:
        return 0, str(exc)


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
    """Return startup authority prerequisites required before live runtime handoff.

    Heartbeat liveness uses a two-tier freshness model:

    1. ``heartbeat_fresh`` — last *successful* Redis refresh is within
       ``heartbeat_max_age_s`` (``max(ttl_s * 2, 30)`` seconds).  This is the
       strict check used when the distributed authority cannot be independently
       verified via Redis.

    2. ``heartbeat_alive_fresh`` — the heartbeat thread updated its
       ``NIJA_WRITER_HEARTBEAT_ALIVE_TS`` (written on *every* loop iteration,
       including failed Redis attempts) within ``heartbeat_alive_max_age_s``
       (``max(ttl_s * 12, 120)`` seconds).  This looser check distinguishes a
       *dead thread* from a *live thread temporarily unable to reach Redis*.

    ``heartbeat_active`` passes when the flag is set AND either freshness tier
    passes.  This prevents transient Redis outages (which set off the 30-second
    success-freshness window but leave the thread alive) from permanently
    blocking execution authority.
    """
    authority = get_distributed_writer_authority_status(force_refresh=force_refresh)
    lease_acquired = _env_truthy("NIJA_WRITER_LEASE_ACQUIRED")
    heartbeat_flag = _env_truthy("NIJA_WRITER_HEARTBEAT_ACTIVE")
    token = os.getenv("NIJA_WRITER_FENCING_TOKEN", "").strip()

    try:
        heartbeat_last_ts = float(os.getenv("NIJA_WRITER_HEARTBEAT_LAST_TS", "0") or 0.0)
    except (TypeError, ValueError):
        heartbeat_last_ts = 0.0

    try:
        heartbeat_alive_ts = float(os.getenv("NIJA_WRITER_HEARTBEAT_ALIVE_TS", "0") or 0.0)
    except (TypeError, ValueError):
        heartbeat_alive_ts = 0.0

    try:
        ttl_s = float(os.getenv("NIJA_WRITER_LOCK_TTL_S", "0") or 0.0)
    except (TypeError, ValueError):
        ttl_s = 0.0

    now = time.time()
    # Strict freshness: last successful heartbeat-to-Redis within 2× TTL (min 30 s).
    heartbeat_max_age_s = max(ttl_s * 2.0, 30.0)
    heartbeat_fresh = heartbeat_last_ts > 0 and (now - heartbeat_last_ts) <= heartbeat_max_age_s

    # Loose liveness: thread iterated (even during Redis failures) within 12× TTL
    # (min 120 s).  Covers the window where Redis is temporarily unreachable but
    # the heartbeat thread is still running and will recover once Redis is back.
    heartbeat_alive_max_age_s = max(ttl_s * 12.0, 120.0)
    heartbeat_alive_fresh = (
        heartbeat_alive_ts > 0 and (now - heartbeat_alive_ts) <= heartbeat_alive_max_age_s
    )
    # Fall back to last_ts if alive_ts was never set (pre-fix deployments).
    if heartbeat_alive_ts <= 0 < heartbeat_last_ts:
        heartbeat_alive_fresh = heartbeat_fresh

    heartbeat_active = heartbeat_flag and (heartbeat_fresh or heartbeat_alive_fresh)

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
        "heartbeat_alive_ts": heartbeat_alive_ts,
        "heartbeat_max_age_s": heartbeat_max_age_s,
        "heartbeat_alive_max_age_s": heartbeat_alive_max_age_s,
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

    if has_execution_authority():
        return

    status = get_startup_execution_authority_prerequisites(force_refresh=False)
    if not status.get("ready"):
        missing = ", ".join(status.get("missing") or []) or "unknown"
        raise RuntimeError(
            "Startup execution authority unavailable "
            f"(missing={missing})"
        )

    if is_seak_halted():
        raise RuntimeError("SEAK halt active")


def assert_execution_dispatch_permitted() -> None:
    """Fail closed unless writer authority and execution scope are both valid."""
    decision = can_execute()
    if not decision.allowed:
        raise ExecutionBlocked(decision.reason)


def _evaluate_stability_authority(
    *,
    runtime_snapshot: RuntimeAuthoritySnapshot,
    state_live_active: bool,
    lease_valid: bool,
    lease_generation_current: bool,
    heartbeat_fresh: bool,
    heartbeat_stage_sufficient: bool,
    broker_health_ok: bool,
    dispatch_enabled: bool,
    circuit_breaker_closed: bool,
) -> StabilityAuthoritySnapshot:
    try:
        try:
            from bot.stability_governor import get_stability_governor
        except ImportError:
            from stability_governor import get_stability_governor  # type: ignore[import]
        decision = get_stability_governor().evaluate(
            runtime_snapshot=runtime_snapshot,
            state_live_active=state_live_active,
            lease_valid=lease_valid,
            lease_generation_current=lease_generation_current,
            heartbeat_fresh=heartbeat_fresh,
            heartbeat_stage_sufficient=heartbeat_stage_sufficient,
            broker_health_ok=broker_health_ok,
            dispatch_enabled=dispatch_enabled,
            circuit_breaker_closed=circuit_breaker_closed,
        )
        return StabilityAuthoritySnapshot(
            allowed=bool(getattr(decision, "allow", False)),
            halt_state=str(getattr(decision, "halt_state", "UNKNOWN")),
            throttle=float(getattr(decision, "throttle", 0.0)),
            size_multiplier=float(getattr(decision, "size_multiplier", 0.0)),
            stress_score=float(getattr(decision, "stress_score", 1.0)),
            collapsed_risk_score=float(getattr(decision, "collapsed_risk_score", 1.0)),
            reason=str(getattr(decision, "reason", "stability_denied")),
        )
    except Exception as exc:
        logger.critical("Stability authority unavailable; failing closed: %s", exc)
        return StabilityAuthoritySnapshot(
            allowed=False,
            halt_state="UNKNOWN",
            throttle=0.0,
            size_multiplier=0.0,
            stress_score=1.0,
            collapsed_risk_score=1.0,
            reason=f"stability_unavailable:{exc}",
        )


def can_execute() -> ExecutionDecision:
    """Canonical execution authority decision for all order-dispatch paths."""
    runtime_snapshot = runtime_authority_snapshot()
    state_live_active = str(os.getenv("NIJA_RUNTIME_TRADING_STATE", "")).strip().upper() == "LIVE_ACTIVE"

    local_generation_raw = (
        os.getenv("NIJA_WRITER_LEASE_GENERATION")
        or os.getenv("NIJA_WRITER_FENCING_TOKEN")
        or "0"
    )
    try:
        local_generation = int(str(local_generation_raw).strip())
    except (TypeError, ValueError):
        local_generation = 0
    current_generation, generation_error = _read_current_lease_generation()
    lease_generation_current = (
        local_generation > 0
        and current_generation > 0
        and local_generation == current_generation
    )
    lease_valid = False
    lease_error = ""
    try:
        assert_distributed_writer_authority()
        lease_valid = True
    except Exception as exc:
        lease_error = str(exc)
        lease_valid = False

    heartbeat_fresh = False
    heartbeat_stage_sufficient = False
    heartbeat_reason = ""
    try:
        try:
            from bot.trading_state_machine import (
                _heartbeat_marker_path,
                _required_heartbeat_stage,
                heartbeat_marker_is_fresh,
                heartbeat_marker_stage_is_sufficient,
            )
        except ImportError:
            from trading_state_machine import (  # type: ignore[import]
                _heartbeat_marker_path,
                _required_heartbeat_stage,
                heartbeat_marker_is_fresh,
                heartbeat_marker_stage_is_sufficient,
            )

        marker_path = _heartbeat_marker_path()
        heartbeat_fresh = heartbeat_marker_is_fresh(marker_path)
        if heartbeat_fresh:
            heartbeat_stage_sufficient = heartbeat_marker_stage_is_sufficient(
                marker_path,
                _required_heartbeat_stage(),
            )
        else:
            heartbeat_stage_sufficient = False
    except Exception as exc:
        heartbeat_reason = str(exc)
        heartbeat_fresh = False
        heartbeat_stage_sufficient = False

    broker_health_ok = bool(runtime_snapshot.dispatch_health_ready)
    dispatch_enabled = bool(runtime_snapshot.dispatch_enabled and has_execution_authority())

    configured_circuit_state = (
        os.getenv("NIJA_EXECUTION_CIRCUIT_STATE", "CLOSED").strip().upper() or "CLOSED"
    )
    if configured_circuit_state not in {"CLOSED", "OPEN", "HALTED", "RECOVERING"}:
        configured_circuit_state = "OPEN"
    recovery_approved = _env_truthy("NIJA_EXECUTION_RECOVERY_APPROVED")

    immediate_halt_triggered = bool(
        (not lease_valid)
        or (not lease_generation_current)
        or (not bool(runtime_snapshot.nonce_ready))
        or ("other-instance" in lease_error.lower())
        or ("mismatch" in lease_error.lower())
    )
    if immediate_halt_triggered and configured_circuit_state == "CLOSED":
        configured_circuit_state = "HALTED"
        os.environ["NIJA_EXECUTION_CIRCUIT_STATE"] = "HALTED"

    circuit_breaker_closed = False
    if configured_circuit_state == "CLOSED":
        circuit_breaker_closed = not bool(runtime_snapshot.kill_switch_active)
    elif configured_circuit_state == "RECOVERING":
        circuit_breaker_closed = bool(
            recovery_approved
            and not bool(runtime_snapshot.kill_switch_active)
            and lease_valid
            and lease_generation_current
            and heartbeat_fresh
            and heartbeat_stage_sufficient
            and broker_health_ok
            and bool(runtime_snapshot.nonce_ready)
        )
    else:
        circuit_breaker_closed = False

    stability = _evaluate_stability_authority(
        runtime_snapshot=runtime_snapshot,
        state_live_active=state_live_active,
        lease_valid=lease_valid,
        lease_generation_current=lease_generation_current,
        heartbeat_fresh=heartbeat_fresh,
        heartbeat_stage_sufficient=heartbeat_stage_sufficient,
        broker_health_ok=broker_health_ok,
        dispatch_enabled=dispatch_enabled,
        circuit_breaker_closed=circuit_breaker_closed,
    )

    checks = (
        ("state.live_active", state_live_active),
        ("lease.valid", lease_valid),
        ("lease.generation_current", lease_generation_current),
        ("heartbeat.fresh", heartbeat_fresh),
        ("heartbeat.stage_sufficient", heartbeat_stage_sufficient),
        ("broker.health_ok", broker_health_ok),
        ("circuit_breaker.closed", circuit_breaker_closed),
        ("dispatch.enabled", dispatch_enabled),
        ("stability.allowed", stability.allowed),
    )

    for check_name, check_ok in checks:
        if not check_ok:
            reason = check_name
            if check_name == "lease.valid" and lease_error:
                reason = f"{check_name}: {lease_error}"
            elif check_name == "lease.generation_current":
                reason = (
                    f"{check_name}: local={local_generation} current={current_generation} "
                    f"detail={generation_error or 'generation_mismatch'}"
                )
            elif check_name.startswith("heartbeat.") and heartbeat_reason:
                reason = f"{check_name}: {heartbeat_reason}"
            elif check_name == "stability.allowed":
                reason = (
                    f"{check_name}: {stability.reason} "
                    f"(state={stability.halt_state} throttle={stability.throttle:.2f} "
                    f"size={stability.size_multiplier:.2f} stress={stability.stress_score:.2f})"
                )
            return ExecutionDecision(
                allowed=False,
                reason=reason,
                circuit_state=configured_circuit_state,
                state_live_active=state_live_active,
                lease_valid=lease_valid,
                lease_generation_current=lease_generation_current,
                heartbeat_fresh=heartbeat_fresh,
                heartbeat_stage_sufficient=heartbeat_stage_sufficient,
                broker_health_ok=broker_health_ok,
                circuit_breaker_closed=circuit_breaker_closed,
                dispatch_enabled=dispatch_enabled,
                stability_allowed=stability.allowed,
                stability_halt_state=stability.halt_state,
                stability_throttle=stability.throttle,
                stability_size_multiplier=stability.size_multiplier,
                stability_stress_score=stability.stress_score,
                stability_collapsed_risk_score=stability.collapsed_risk_score,
                stability_reason=stability.reason,
            )

    # ── Stability governor HALT gate (Phase 3 — disabled by default) ────────────
    # Consulted only when NIJA_STABILITY_GOVERNOR_HALT_ENABLED is explicitly set so
    # that Phase 1/2 (observe + guarded) do not block dispatch paths.  The governor
    # is fail-open: any exception here is silently absorbed so it cannot accidentally
    # block execution when unavailable.
    if _env_truthy("NIJA_STABILITY_GOVERNOR_HALT_ENABLED"):
        try:
            try:
                from bot.stability_governor import get_stability_governor
            except ImportError:
                from stability_governor import get_stability_governor  # type: ignore[import]
            _sg = get_stability_governor()
            if _sg.is_halted():
                _sg_snap = _sg.get_snapshot()
                return ExecutionDecision(
                    allowed=False,
                    reason=f"stability_governor:HALT:{_sg_snap.reason}",
                    circuit_state=configured_circuit_state,
                    state_live_active=state_live_active,
                    lease_valid=lease_valid,
                    lease_generation_current=lease_generation_current,
                    heartbeat_fresh=heartbeat_fresh,
                    heartbeat_stage_sufficient=heartbeat_stage_sufficient,
                    broker_health_ok=broker_health_ok,
                    circuit_breaker_closed=circuit_breaker_closed,
                    dispatch_enabled=dispatch_enabled,
                )
        except Exception as _sg_exc:
            logger.debug("StabilityGovernor HALT check unavailable (fail-open): %s", _sg_exc)

    return ExecutionDecision(
        allowed=True,
        reason="allowed",
        circuit_state=configured_circuit_state,
        state_live_active=state_live_active,
        lease_valid=lease_valid,
        lease_generation_current=lease_generation_current,
        heartbeat_fresh=heartbeat_fresh,
        heartbeat_stage_sufficient=heartbeat_stage_sufficient,
        broker_health_ok=broker_health_ok,
        circuit_breaker_closed=circuit_breaker_closed,
        dispatch_enabled=dispatch_enabled,
        stability_allowed=stability.allowed,
        stability_halt_state=stability.halt_state,
        stability_throttle=stability.throttle,
        stability_size_multiplier=stability.size_multiplier,
        stability_stress_score=stability.stress_score,
        stability_collapsed_risk_score=stability.collapsed_risk_score,
        stability_reason=stability.reason,
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
        ready = bool(snapshot.execution_permitted)
        return RuntimeAuthoritySnapshot(
            ready=ready,
            authority_ready=bool(snapshot.authority_ready),
            nonce_ready=bool(snapshot.nonce_ready),
            dispatch_health_ready=bool(snapshot.dispatch_health_ready),
            dispatch_enabled=bool(snapshot.dispatch_enabled),
            kill_switch_active=bool(snapshot.kill_switch_active),
            coordinator_state=str(snapshot.coordinator_state),
            runtime_state=str(snapshot.runtime_authority_state),
            reason=str(snapshot.runtime_authority_reason),
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
            runtime_state="DEGRADED",
            reason="runtime_authority_snapshot_unavailable",
        )
