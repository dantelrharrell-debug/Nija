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
import json
from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
from collections import deque
from typing import Any, Dict, Iterator, Optional

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
_STARTUP_EXECUTION_PROBE_REASON: ContextVar[str] = ContextVar(
    "nija_startup_execution_probe_reason",
    default="",
)
_STARTUP_EXECUTION_PROBE_REASONS = {
    "HEARTBEAT_TRADE",
    "HEARTBEAT_TRADE_CLOSE",
}

_FENCE_VERIFY_LOCK = threading.Lock()
_FENCE_LAST_CHECK_TS: float = 0.0
_FENCE_LAST_OK: bool = False
_FENCE_LAST_ERR: str = ""
_FENCE_RECOVER_NEXT_ATTEMPT_TS: float = 0.0

# ── Telemetry emit throttle (Fix #4) ─────────────────────────────────────────
# Limit how often _emit_trade_admission_telemetry fires per gate stage.
# The hot path (can_execute on every admission check) would otherwise flood
# logs on sustained BOOT/WARM lifecycle blocks.  One emission per stage per
# _TELEMETRY_THROTTLE_S is sufficient for observability without log storm.
_TELEMETRY_THROTTLE_S: float = 1.0
_TELEMETRY_LAST_EMIT: dict[str, float] = {}
_TELEMETRY_EMIT_LOCK = threading.Lock()

logger = logging.getLogger("nija.execution_authority")

PRE_TRADE_VALIDATOR_VERSION = "v1"
PRE_TRADE_GATE_ORDER = (
    "lifecycle.phase",
    "state.live_active",
    "lease.valid",
    "lease.generation_current",
    "nonce.authority",
    "heartbeat.fresh",
    "heartbeat.stage_sufficient",
    "broker.health_ok",
    "circuit_breaker.closed",
    "dispatch.enabled",
    "stability.allowed",
    "margin.critical_ok",
    "margin.maintenance_ok",
)
_PRE_TRADE_GATE_REASON_CODES = {
    "lifecycle.phase": "lifecycle_phase_not_live",
    "state.live_active": "state_not_live_active",
    "lease.valid": "lease_invalid",
    "lease.generation_current": "lease_generation_mismatch",
    "nonce.authority": "nonce_authority_missing",
    "heartbeat.fresh": "heartbeat_stale",
    "heartbeat.stage_sufficient": "heartbeat_stage_insufficient",
    "broker.health_ok": "broker_health_not_ready",
    "circuit_breaker.closed": "circuit_breaker_open",
    "dispatch.enabled": "dispatch_scope_missing",
    "stability.allowed": "stability_denied",
    "margin.critical_ok": "margin_critical",
    "margin.maintenance_ok": "margin_maintenance_low",
}
_PRE_TRADE_TRACE_MAX = max(
    50,
    int(float(os.getenv("NIJA_PRE_TRADE_TRACE_BUFFER_SIZE", "400") or "400")),
)
_PRE_TRADE_TRACE_BUFFER: deque[Dict[str, Any]] = deque(maxlen=_PRE_TRADE_TRACE_MAX)
_PRE_TRADE_TRACE_LOCK = threading.Lock()
_PRE_TRADE_TRACE_EMITTED_BY_ATTEMPT: dict[str, float] = {}
_PRE_TRADE_TRACE_EMIT_LOCK = threading.Lock()


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
    lifecycle_phase: str = "BOOT"
    """Coarse lifecycle phase: BOOT, WARM, or LIVE.

    This is the top-level execution gate.  Execution is only permitted when
    ``lifecycle_phase == "LIVE"``.  Startup probes are the only explicit
    exception for pre-LIVE submissions.
    """


@dataclass(frozen=True)
class ExecutionDecision:
    allowed: bool
    reason: str
    circuit_state: str
    state_live_active: bool
    lease_valid: bool
    lease_generation_current: bool
    nonce_ready: bool
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
    first_failed_gate: str = ""
    reason_code: str = ""
    reason_detail: str = ""
    validator_version: str = PRE_TRADE_VALIDATOR_VERSION
    lifecycle_phase: str = "BOOT"
    """Coarse lifecycle phase captured at decision time.

    ``BOOT`` or ``WARM`` indicates the execution was denied by the lifecycle
    gate before any lower-level checks were reached.  ``LIVE`` means the
    lifecycle gate passed and denial (if any) came from a lower-level gate.
    """


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


def _gate_reason_code(gate_name: str, default: str = "execution_blocked") -> str:
    return str(_PRE_TRADE_GATE_REASON_CODES.get(gate_name) or default)


def _decision_gate_status(decision: ExecutionDecision) -> Dict[str, bool]:
    reason_lower = str(getattr(decision, "reason_detail", None) or getattr(decision, "reason", None) or "").lower()
    margin_critical_ok = "margin_critical" not in reason_lower
    margin_maintenance_ok = "margin_maintenance_low" not in reason_lower
    if str(getattr(decision, "first_failed_gate", None) or "") == "margin.critical_ok":
        margin_critical_ok = False
    if str(getattr(decision, "first_failed_gate", None) or "") == "margin.maintenance_ok":
        margin_maintenance_ok = False
    return {
        "lifecycle.phase": str(getattr(decision, "lifecycle_phase", "BOOT")).upper() == "LIVE",
        "state.live_active": bool(getattr(decision, "state_live_active", False)),
        "lease.valid": bool(getattr(decision, "lease_valid", False)),
        "lease.generation_current": bool(getattr(decision, "lease_generation_current", False)),
        "nonce.authority": bool(getattr(decision, "nonce_ready", False)),
        "heartbeat.fresh": bool(getattr(decision, "heartbeat_fresh", False)),
        "heartbeat.stage_sufficient": bool(getattr(decision, "heartbeat_stage_sufficient", False)),
        "broker.health_ok": bool(getattr(decision, "broker_health_ok", False)),
        "circuit_breaker.closed": bool(getattr(decision, "circuit_breaker_closed", False)),
        "dispatch.enabled": bool(getattr(decision, "dispatch_enabled", False)),
        "stability.allowed": bool(getattr(decision, "stability_allowed", False)),
        "margin.critical_ok": bool(margin_critical_ok),
        "margin.maintenance_ok": bool(margin_maintenance_ok),
    }


def _first_failed_gate_for_decision(decision: ExecutionDecision) -> Optional[str]:
    gate_status = _decision_gate_status(decision)
    for gate in PRE_TRADE_GATE_ORDER:
        if gate in gate_status and not bool(gate_status[gate]):
            return gate
        if gate in {"margin.critical_ok", "margin.maintenance_ok"}:
            # Margin gates are represented in reason fields when they block.
            reason = str(getattr(decision, "reason_detail", None) or getattr(decision, "reason", None) or "").lower()
            if gate == "margin.critical_ok" and "margin_critical" in reason:
                return gate
            if gate == "margin.maintenance_ok" and "margin_maintenance_low" in reason:
                return gate
    return None


def _correlation_envelope() -> Dict[str, str]:
    try:
        from bot.runtime_correlation import get_runtime_correlation
        return dict(get_runtime_correlation() or {})
    except Exception:
        return {}


def emit_pretrade_execution_validator_trace(
    decision: ExecutionDecision,
    *,
    symbol: str = "",
    side: str = "",
    size: float = 0.0,
    order_id: str = "",
    attempt_id: str = "",
    terminal_surface: str = "can_execute",
    block_reason_code: str = "",
    block_reason_detail: str = "",
    first_failed_gate: str = "",
) -> Optional[Dict[str, Any]]:
    """Emit and store one canonical terminal validator trace line."""
    envelope = _correlation_envelope()
    trace_attempt_id = str(attempt_id or order_id or envelope.get("intent_id") or "").strip()
    if trace_attempt_id:
        with _PRE_TRADE_TRACE_EMIT_LOCK:
            if trace_attempt_id in _PRE_TRADE_TRACE_EMITTED_BY_ATTEMPT:
                return None
            _PRE_TRADE_TRACE_EMITTED_BY_ATTEMPT[trace_attempt_id] = time.monotonic()
            if len(_PRE_TRADE_TRACE_EMITTED_BY_ATTEMPT) > 4000:
                cutoff = time.monotonic() - 1200.0
                _existing = dict(_PRE_TRADE_TRACE_EMITTED_BY_ATTEMPT)
                _PRE_TRADE_TRACE_EMITTED_BY_ATTEMPT.clear()
                _PRE_TRADE_TRACE_EMITTED_BY_ATTEMPT.update({
                    k: v
                    for k, v in _existing.items()
                    if v >= cutoff
                })

    gate_status = _decision_gate_status(decision)
    decision_value = "ALLOW" if bool(decision.allowed) else "BLOCK"
    terminal_first_failed = (
        str(first_failed_gate or getattr(decision, "first_failed_gate", None) or _first_failed_gate_for_decision(decision) or "").strip()
        or None
    )
    reason_detail = str(
        block_reason_detail
        or getattr(decision, "reason_detail", None)
        or getattr(decision, "reason", None)
        or ("allowed" if decision.allowed else "blocked")
    )
    reason_code = str(
        block_reason_code
        or getattr(decision, "reason_code", None)
        or (_gate_reason_code(str(terminal_first_failed)) if terminal_first_failed else "allowed")
    )
    payload: Dict[str, Any] = {
        "validator_version": PRE_TRADE_VALIDATOR_VERSION,
        "decision": decision_value,
        "first_failed_gate": terminal_first_failed if decision_value == "BLOCK" else None,
        "reason_code": reason_code if decision_value == "BLOCK" else "allowed",
        "reason_detail": reason_detail,
        "lifecycle_phase": str(getattr(decision, "lifecycle_phase", "BOOT")),
        "circuit_state": str(getattr(decision, "circuit_state", "")),
        "gates": gate_status,
        "symbol": str(symbol or ""),
        "side": str(side or ""),
        "size": float(size or 0.0),
        "order_id": str(order_id or ""),
        "attempt_id": trace_attempt_id or "",
        "terminal_surface": str(terminal_surface or "can_execute"),
        "correlation": envelope,
        "timestamp": time.time(),
    }
    with _PRE_TRADE_TRACE_LOCK:
        _PRE_TRADE_TRACE_BUFFER.append(payload)
    logger.info(
        "PRE_TRADE_EXECUTION_VALIDATOR_TRACE %s",
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
    )
    return payload


def get_pretrade_execution_validator_traces(limit: int = 25) -> list[Dict[str, Any]]:
    with _PRE_TRADE_TRACE_LOCK:
        rows = list(_PRE_TRADE_TRACE_BUFFER)[-max(1, int(limit or 1)):]
    return list(reversed(rows))


def get_latest_pretrade_execution_validator_trace() -> Optional[Dict[str, Any]]:
    with _PRE_TRADE_TRACE_LOCK:
        if not _PRE_TRADE_TRACE_BUFFER:
            return None
        return dict(_PRE_TRADE_TRACE_BUFFER[-1])


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


def _runtime_nonce_authority_status() -> tuple[bool, str]:
    """Return live nonce authority status for the active Kraken runtime."""
    try:
        try:
            from bot import trading_state_machine as _tsm
        except ImportError:
            import trading_state_machine as _tsm  # type: ignore[import]
    except Exception as exc:
        return False, f"nonce_runtime_gate_unavailable:{exc}"

    gate_checks = (
        ("nonce_sync", getattr(_tsm, "_nonce_sync_gate", None)),
        ("nonce_lease", getattr(_tsm, "_nonce_writer_lease_gate", None)),
    )
    for gate_name, gate_fn in gate_checks:
        if not callable(gate_fn):
            return False, f"{gate_name}_gate_unavailable"
        try:
            ok, detail = gate_fn()
        except Exception as exc:
            return False, f"{gate_name}_gate_exception:{exc}"
        if not bool(ok):
            return False, f"{gate_name}:{detail or 'blocked'}"
    return True, ""


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
    This function enforces strict distributed fencing by default.  Three
    operator-controlled bypass flags can override this behaviour when stale
    locks from a previous Railway deployment are blocking startup:

    - ``NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true``  — skip the check entirely
      and proceed as the writer.  Use only when you are certain no other live
      instance is running.
    - ``NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true`` — fall back to local
      writer authority when the distributed lock cannot be verified (missing
      token, Redis unreachable, or fencing mismatch).
    - ``NIJA_AUTO_CLEAR_STALE_RAILWAY_LOCK=true`` — attempt to delete the
      stale Redis lock key before falling back, allowing this instance to
      re-acquire it on the next heartbeat cycle.

    All bypass paths emit a WARNING-level log so the operator is aware that
    strict single-writer enforcement is not active.
    """
    global _FENCE_LAST_CHECK_TS, _FENCE_LAST_OK, _FENCE_LAST_ERR

    import hashlib

    # ── Operator bypass: skip the entire distributed check ────────────────────
    if _env_truthy("NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK"):
        logger.warning(
            "STARTUP_OBSERVER_STANDBY: NIJA_UNSAFE_BYPASS_DISTRIBUTED_LOCK=true — "
            "skipping distributed writer authority check. "
            "Proceeding as local writer. Ensure no other live instance is running."
        )
        with _FENCE_VERIFY_LOCK:
            _FENCE_LAST_CHECK_TS = time.monotonic()
            _FENCE_LAST_OK = True
            _FENCE_LAST_ERR = ""
        return

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

    # Fencing token is mandatory unless the local-fallback bypass is active.
    token = os.getenv("NIJA_WRITER_FENCING_TOKEN", "").strip()
    if not token:
        if _env_truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK"):
            logger.warning(
                "STARTUP_OBSERVER_STANDBY: STRICT_SINGLE_WRITER_REQUIRED: "
                "NIJA_WRITER_FENCING_TOKEN is not set but "
                "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true — "
                "using local writer fallback. Trading will proceed without "
                "distributed lock verification."
            )
            with _FENCE_VERIFY_LOCK:
                _FENCE_LAST_CHECK_TS = time.monotonic()
                _FENCE_LAST_OK = True
                _FENCE_LAST_ERR = ""
            return
        _err = (
            "STARTUP_OBSERVER_STANDBY: STRICT_SINGLE_WRITER_REQUIRED: "
            "NIJA_WRITER_FENCING_TOKEN is not set. "
            "Distributed writer authority requires a valid fencing token. "
            "Ensure the bot acquired a Redis writer lease at startup. "
            "Set NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true to use local fallback."
        )
        with _FENCE_VERIFY_LOCK:
            _FENCE_LAST_CHECK_TS = time.monotonic()
            _FENCE_LAST_OK = False
            _FENCE_LAST_ERR = _err
        raise RuntimeError(_err)

    # Redis URL is mandatory unless the local-fallback bypass is active.
    if not redis_url:
        if _env_truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK"):
            logger.warning(
                "STARTUP_OBSERVER_STANDBY: STRICT_SINGLE_WRITER_REQUIRED: "
                "Redis URL is not configured but "
                "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true — "
                "using local writer fallback. Trading will proceed without "
                "distributed lock verification."
            )
            with _FENCE_VERIFY_LOCK:
                _FENCE_LAST_CHECK_TS = time.monotonic()
                _FENCE_LAST_OK = True
                _FENCE_LAST_ERR = ""
            return
        _err = (
            "STARTUP_OBSERVER_STANDBY: STRICT_SINGLE_WRITER_REQUIRED: "
            "Redis URL is not configured. "
            "Distributed writer authority requires Redis connectivity. "
            "Set NIJA_REDIS_URL to a valid rediss:// endpoint or set "
            "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true to use local fallback."
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
            cached_err = _FENCE_LAST_ERR or "distributed writer fence verification cached failure"
            # Honour bypass flags even for cached failures so a flag change
            # takes effect without waiting for the TTL to expire.
            if _env_truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK"):
                logger.warning(
                    "STARTUP_OBSERVER_STANDBY: STRICT_SINGLE_WRITER_REQUIRED: "
                    "cached authority failure but NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true — "
                    "using local writer fallback (cached_err=%s)",
                    cached_err,
                )
                _FENCE_LAST_OK = True
                _FENCE_LAST_ERR = ""
                return
            raise RuntimeError(cached_err)

    try:
        client = _connect_redis_for_authority(redis_url, timeout_s=2)
        current = client.get(lock_key)
        current_token = ""
        if current is not None:
            # decode_responses=True should give str, but guard against bytes
            # in case a connection with different settings is reused.
            if isinstance(current, bytes):
                current = current.decode("utf-8", errors="replace")
            if isinstance(current, str) and current:
                current_token = current.split(":", 1)[0]

        # ── Missing-key recovery ──────────────────────────────────────────────
        # When the lock key is absent (expired TTL or transient Redis flush) but
        # this process still holds the correct fencing token, attempt a one-shot
        # atomic re-acquisition using SET NX.  This mirrors the heartbeat's own
        # re-acquisition path and prevents a spurious hard-stop when the key
        # simply expired between heartbeat renewals.
        #
        # Safety: SET NX is atomic — if another process wins the race it holds a
        # different token and the subsequent comparison will still fail closed.
        if current is None and token:
            try:
                ttl_s = max(
                    30,
                    int(os.getenv("NIJA_WRITER_LOCK_TTL_S", "30") or 30),
                )
                owner_id = os.getenv("NIJA_WRITER_OWNER_ID", "recovered")
                lock_value = f"{token}:{owner_id}"
                reacquired = client.set(lock_key, lock_value, ex=ttl_s, nx=True)
                if reacquired:
                    current_token = token
                    logger.warning(
                        "assert_distributed_writer_authority: lock key was missing; "
                        "re-acquired atomically with same fencing token "
                        "(lock_key=%s token_prefix=%s ttl_s=%d)",
                        lock_key,
                        token[:8],
                        ttl_s,
                    )
                else:
                    # Another process won the NX race — read back the new holder.
                    new_current = client.get(lock_key)
                    if new_current is not None:
                        if isinstance(new_current, bytes):
                            new_current = new_current.decode("utf-8", errors="replace")
                        if isinstance(new_current, str) and new_current:
                            current_token = new_current.split(":", 1)[0]
            except Exception as _reacq_exc:
                logger.warning(
                    "assert_distributed_writer_authority: lock re-acquisition attempt failed: %s",
                    _reacq_exc,
                )

        ok = (current_token == token)
        err = ""
        if not ok:
            err = (
                "STARTUP_OBSERVER_STANDBY: STRICT_SINGLE_WRITER_REQUIRED: "
                "another instance owns writer authority — "
                f"expected_token={token} current_token={current_token or '<missing>'} "
                f"lock_key={lock_key}"
            )

            # ── Auto-clear stale lock ─────────────────────────────────────────
            # When NIJA_AUTO_CLEAR_STALE_RAILWAY_LOCK=true, attempt to delete
            # the stale lock so this instance can re-acquire it on the next
            # heartbeat cycle.  Only safe when the operator is certain the
            # previous holder is no longer running (e.g. after a Railway redeploy).
            if _env_truthy("NIJA_AUTO_CLEAR_STALE_RAILWAY_LOCK"):
                try:
                    deleted = client.delete(lock_key)
                    if deleted:
                        logger.warning(
                            "STARTUP_OBSERVER_STANDBY: NIJA_AUTO_CLEAR_STALE_RAILWAY_LOCK=true — "
                            "deleted stale writer lock (lock_key=%s previous_token=%s). "
                            "This instance will re-acquire the lock on the next heartbeat cycle.",
                            lock_key,
                            current_token or "<missing>",
                        )
                        # Treat as ok so this cycle can proceed; the heartbeat
                        # will write a fresh lock entry with the current token.
                        ok = True
                        err = ""
                    else:
                        logger.warning(
                            "STARTUP_OBSERVER_STANDBY: NIJA_AUTO_CLEAR_STALE_RAILWAY_LOCK=true — "
                            "lock key already absent (lock_key=%s); proceeding.",
                            lock_key,
                        )
                        ok = True
                        err = ""
                except Exception as _del_exc:
                    logger.warning(
                        "STARTUP_OBSERVER_STANDBY: NIJA_AUTO_CLEAR_STALE_RAILWAY_LOCK=true — "
                        "failed to delete stale lock (lock_key=%s): %s",
                        lock_key,
                        _del_exc,
                    )

            # ── Local-fallback bypass ─────────────────────────────────────────
            if not ok and _env_truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK"):
                logger.warning(
                    "STARTUP_OBSERVER_STANDBY: STRICT_SINGLE_WRITER_REQUIRED: "
                    "another instance owns writer authority but "
                    "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true — "
                    "using local writer fallback. "
                    "Trading will proceed without distributed lock verification. "
                    "(lock_key=%s expected_token=%s current_token=%s)",
                    lock_key,
                    token,
                    current_token or "<missing>",
                )
                ok = True
                err = ""

        with _FENCE_VERIFY_LOCK:
            _FENCE_LAST_CHECK_TS = time.monotonic()
            _FENCE_LAST_OK = ok
            _FENCE_LAST_ERR = err

        if not ok:
            raise RuntimeError(err)

    except RuntimeError:
        raise
    except Exception as exc:
        _err = (
            "STARTUP_OBSERVER_STANDBY: STRICT_SINGLE_WRITER_REQUIRED: "
            f"Redis execution authority unavailable — {exc}"
        )
        if _env_truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK"):
            logger.warning(
                "%s — NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK=true, using local writer fallback.",
                _err,
            )
            with _FENCE_VERIFY_LOCK:
                _FENCE_LAST_CHECK_TS = time.monotonic()
                _FENCE_LAST_OK = True
                _FENCE_LAST_ERR = ""
            return
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


@contextmanager
def startup_execution_probe_scope(reason: str) -> Iterator[None]:
    """Mark startup probe reason for narrowly scoped pre-live verification submits."""
    normalized_reason = str(reason or "").strip().upper()
    token = _STARTUP_EXECUTION_PROBE_REASON.set(normalized_reason)
    try:
        yield
    finally:
        _STARTUP_EXECUTION_PROBE_REASON.reset(token)


def can_execute_startup_probe() -> tuple[bool, str]:
    """Allow only whitelisted startup probe submits after authority checks."""
    probe_reason = str(_STARTUP_EXECUTION_PROBE_REASON.get() or "").strip().upper()
    if probe_reason not in _STARTUP_EXECUTION_PROBE_REASONS:
        return False, "probe_reason_not_whitelisted"
    try:
        assert_startup_write_authority()
    except Exception as exc:
        return False, str(exc)
    return True, probe_reason


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


def _emit_trade_admission_telemetry(
    *,
    reason: str,
    drop_bucket: str | None = None,
    governor_mode: str = "UNKNOWN",
    confidence: float = 0.0,
    threshold: float = 0.0,
    stage: str = "control_compiler",
) -> None:
    # Edge-trigger throttle: suppress duplicate emissions for the same gate
    # stage within _TELEMETRY_THROTTLE_S seconds so that a sustained block
    # (e.g. lifecycle_phase=BOOT for tens of seconds) does not flood logs or
    # the drop-counter on every trade-admission poll cycle.
    now = time.time()
    with _TELEMETRY_EMIT_LOCK:
        last = _TELEMETRY_LAST_EMIT.get(stage, 0.0)
        if now - last < _TELEMETRY_THROTTLE_S:
            return
        _TELEMETRY_LAST_EMIT[stage] = now

    logger.info(
        "ExecutionDecision(stage=%s, allow=%s, reason=%s, confidence=%.4f, threshold=%.4f, governor_mode=%s)",
        stage,
        False,
        reason,
        float(confidence),
        float(threshold),
        governor_mode,
    )
    if not drop_bucket:
        return
    try:
        try:
            from bot.control_compiler import get_control_compiler
        except ImportError:
            from control_compiler import get_control_compiler  # type: ignore[import]
        get_control_compiler().record_external_execution_drop(
            reason=reason,
            drop_bucket=drop_bucket,
            governor_mode=governor_mode,
            confidence=float(confidence),
            threshold=float(threshold),
            stage=stage,
        )
    except Exception as exc:
        logger.debug("Execution drop telemetry emit failed: %s", exc)


def can_execute() -> ExecutionDecision:
    """Canonical execution authority decision for all order-dispatch paths."""
    runtime_snapshot = runtime_authority_snapshot()

    # ── Gate 0: lifecycle phase ───────────────────────────────────────────────
    # The lifecycle phase is the top-level execution primitive.  Normal order
    # dispatch is only allowed in the LIVE phase (runtime authority state ==
    # EXECUTING, meaning the activation commit is in place and trading is
    # active).  BOOT and WARM phases block execution unconditionally here;
    # startup probes bypass this via can_execute_startup_probe().
    try:
        from bot.startup_coordinator import LifecyclePhase
    except ImportError:
        from startup_coordinator import LifecyclePhase  # type: ignore[import]

    current_lifecycle_phase = str(runtime_snapshot.lifecycle_phase)
    if current_lifecycle_phase != LifecyclePhase.LIVE.value:
        reason_detail = f"lifecycle_phase:{current_lifecycle_phase}"
        _emit_trade_admission_telemetry(
            reason=reason_detail,
            drop_bucket="lifecycle_phase",
            stage="lifecycle_gate",
        )
        return ExecutionDecision(
            allowed=False,
            reason=reason_detail,
            circuit_state="CLOSED",
            state_live_active=False,
            lease_valid=False,
            lease_generation_current=False,
            nonce_ready=bool(runtime_snapshot.nonce_ready),
            heartbeat_fresh=False,
            heartbeat_stage_sufficient=False,
            broker_health_ok=bool(runtime_snapshot.dispatch_health_ready),
            circuit_breaker_closed=False,
            dispatch_enabled=bool(runtime_snapshot.dispatch_enabled and has_execution_authority()),
            stability_allowed=False,
            stability_halt_state="UNKNOWN",
            stability_throttle=0.0,
            stability_size_multiplier=0.0,
            stability_stress_score=1.0,
            stability_collapsed_risk_score=1.0,
            stability_reason="lifecycle_phase_not_live",
            first_failed_gate="lifecycle.phase",
            reason_code=_gate_reason_code("lifecycle.phase"),
            reason_detail=reason_detail,
            lifecycle_phase=current_lifecycle_phase,
        )

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
    startup_nonce_ready = bool(runtime_snapshot.nonce_ready)
    runtime_nonce_ready, runtime_nonce_error = _runtime_nonce_authority_status()
    nonce_ready = bool(startup_nonce_ready and runtime_nonce_ready)

    configured_circuit_state = (
        os.getenv("NIJA_EXECUTION_CIRCUIT_STATE", "CLOSED").strip().upper() or "CLOSED"
    )
    if configured_circuit_state not in {"CLOSED", "OPEN", "HALTED", "RECOVERING"}:
        configured_circuit_state = "OPEN"
    recovery_approved = _env_truthy("NIJA_EXECUTION_RECOVERY_APPROVED")

    immediate_halt_triggered = bool(
        (not lease_valid)
        or (not lease_generation_current)
        or (not nonce_ready)
        or ("other-instance" in lease_error.lower())
        or ("mismatch" in lease_error.lower())
    )
    if immediate_halt_triggered and configured_circuit_state == "CLOSED":
        configured_circuit_state = "HALTED"
        os.environ["NIJA_EXECUTION_CIRCUIT_STATE"] = "HALTED"

    # ── Auto-reset HALTED circuit when lease is fully recovered ──────────────
    # If the circuit was halted due to a previous fencing mismatch (missing lock
    # key) and the lease has since been re-acquired successfully, reset the
    # circuit back to CLOSED so trading can resume without a manual operator
    # intervention.  Only reset when the halt was caused by a lease/fencing
    # issue (not an explicit OPEN or operator-set HALTED for other reasons).
    if (
        configured_circuit_state == "HALTED"
        and lease_valid
        and lease_generation_current
        and nonce_ready
        and not ("other-instance" in lease_error.lower())
    ):
        configured_circuit_state = "CLOSED"
        os.environ["NIJA_EXECUTION_CIRCUIT_STATE"] = "CLOSED"
        logger.warning(
            "can_execute: circuit auto-reset HALTED→CLOSED after successful "
            "lease re-acquisition (lease_valid=True, generation_current=True)"
        )

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
            and nonce_ready
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
        ("nonce.authority", nonce_ready),
        ("heartbeat.fresh", heartbeat_fresh),
        ("heartbeat.stage_sufficient", heartbeat_stage_sufficient),
        ("broker.health_ok", broker_health_ok),
        ("circuit_breaker.closed", circuit_breaker_closed),
        ("dispatch.enabled", dispatch_enabled),
        ("stability.allowed", stability.allowed),
    )

    for check_name, check_ok in checks:
        if not check_ok:
            reason_detail = check_name
            if check_name == "lease.valid" and lease_error:
                reason_detail = f"{check_name}: {lease_error}"
            elif check_name == "lease.generation_current":
                reason_detail = (
                    f"{check_name}: local={local_generation} current={current_generation} "
                    f"detail={generation_error or 'generation_mismatch'}"
                )
            elif check_name == "nonce.authority":
                nonce_detail_parts = []
                if not startup_nonce_ready:
                    nonce_detail_parts.append("startup_snapshot_not_ready")
                if runtime_nonce_error:
                    nonce_detail_parts.append(runtime_nonce_error)
                if nonce_detail_parts:
                    reason_detail = f"{check_name}: {'; '.join(nonce_detail_parts)}"
            elif check_name.startswith("heartbeat.") and heartbeat_reason:
                reason_detail = f"{check_name}: {heartbeat_reason}"
            elif check_name == "stability.allowed":
                reason_detail = (
                    f"{check_name}: {stability.reason} "
                    f"(state={stability.halt_state} throttle={stability.throttle:.2f} "
                    f"size={stability.size_multiplier:.2f} stress={stability.stress_score:.2f})"
                )
            drop_bucket = None
            governor_mode = "NORMAL"
            telemetry_reason = reason_detail
            if check_name == "stability.allowed":
                drop_bucket = "governor_guarded"
                governor_mode = stability.halt_state or "GUARDED"
                telemetry_reason = "governor_guarded"
            elif check_name == "broker.health_ok":
                drop_bucket = "broker_health"
                telemetry_reason = "broker_health"
            elif check_name == "nonce.authority":
                drop_bucket = "nonce_authority"
                telemetry_reason = "nonce_authority"
            _emit_trade_admission_telemetry(
                reason=telemetry_reason,
                drop_bucket=drop_bucket,
                governor_mode=governor_mode,
            )
            return ExecutionDecision(
                allowed=False,
                reason=reason_detail,
                circuit_state=configured_circuit_state,
                state_live_active=state_live_active,
                lease_valid=lease_valid,
                lease_generation_current=lease_generation_current,
                nonce_ready=nonce_ready,
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
                first_failed_gate=check_name,
                reason_code=_gate_reason_code(check_name),
                reason_detail=reason_detail,
                lifecycle_phase=current_lifecycle_phase,
            )

    # ── Stability governor HALT gate (Phase 3 — disabled by default) ────────────
    # Consulted only when NIJA_STABILITY_GOVERNOR_HALT_ENABLED is explicitly set so
    # that Phase 1/2 (observe + guarded) do not block dispatch paths. Exceptions in
    # this gate fail closed to prevent silent authority bypasses.
    if _env_truthy("NIJA_STABILITY_GOVERNOR_HALT_ENABLED"):
        try:
            try:
                from bot.stability_governor import get_stability_governor
            except ImportError:
                from stability_governor import get_stability_governor  # type: ignore[import]
            _sg = get_stability_governor()
            if _sg.is_halted():
                _sg_snap = _sg.get_snapshot()
                _emit_trade_admission_telemetry(
                    reason="governor_guarded",
                    drop_bucket="governor_guarded",
                    governor_mode="HALT",
                )
                return ExecutionDecision(
                    allowed=False,
                    reason=f"stability_governor:HALT:{_sg_snap.reason}",
                    circuit_state=configured_circuit_state,
                    state_live_active=state_live_active,
                    lease_valid=lease_valid,
                    lease_generation_current=lease_generation_current,
                    nonce_ready=nonce_ready,
                    heartbeat_fresh=heartbeat_fresh,
                    heartbeat_stage_sufficient=heartbeat_stage_sufficient,
                    broker_health_ok=broker_health_ok,
                    circuit_breaker_closed=circuit_breaker_closed,
                    dispatch_enabled=dispatch_enabled,
                    stability_allowed=False,
                    stability_halt_state="HALT",
                    stability_throttle=0.0,
                    stability_size_multiplier=0.0,
                    stability_stress_score=1.0,
                    stability_collapsed_risk_score=1.0,
                    stability_reason=f"stability_governor_halt:{_sg_snap.reason}",
                    first_failed_gate="stability.allowed",
                    reason_code=_gate_reason_code("stability.allowed"),
                    reason_detail=f"stability_governor:HALT:{_sg_snap.reason}",
                    lifecycle_phase=current_lifecycle_phase,
                )
        except Exception as _sg_exc:
            _reason_detail = f"stability_halt_gate_unavailable:{_sg_exc}"
            logger.error("StabilityGovernor HALT check unavailable (fail-closed): %s", _sg_exc)
            _emit_trade_admission_telemetry(
                reason="governor_guarded",
                drop_bucket="governor_guarded",
                governor_mode="HALT_UNAVAILABLE",
            )
            return ExecutionDecision(
                allowed=False,
                reason=_reason_detail,
                circuit_state=configured_circuit_state,
                state_live_active=state_live_active,
                lease_valid=lease_valid,
                lease_generation_current=lease_generation_current,
                nonce_ready=nonce_ready,
                heartbeat_fresh=heartbeat_fresh,
                heartbeat_stage_sufficient=heartbeat_stage_sufficient,
                broker_health_ok=broker_health_ok,
                circuit_breaker_closed=circuit_breaker_closed,
                dispatch_enabled=dispatch_enabled,
                stability_allowed=False,
                stability_halt_state="HALT_UNAVAILABLE",
                stability_throttle=0.0,
                stability_size_multiplier=0.0,
                stability_stress_score=1.0,
                stability_collapsed_risk_score=1.0,
                stability_reason=_reason_detail,
                first_failed_gate="stability.allowed",
                reason_code=_gate_reason_code("stability.allowed"),
                reason_detail=_reason_detail,
                lifecycle_phase=current_lifecycle_phase,
            )

    # ── Margin health gate (ledger-authoritative boundary) ───────────────────
    # Deterministic authority boundary:
    #   - Margin ledger/engine computes risk truth.
    #   - Execution authority consumes that truth and never recomputes margin math.
    # Gate fails closed on engine exceptions to avoid silent authority bypasses.
    if _env_truthy("NIJA_KRAKEN_MARGIN_ENABLED"):
        try:
            try:
                from bot.kraken_margin_engine import get_margin_engine
            except ImportError:
                from kraken_margin_engine import get_margin_engine  # type: ignore[import]
            _mg = get_margin_engine()
            _mg_snap = _mg.get_health_snapshot(adapter=None)
            _has_margin_exposure = float(getattr(_mg_snap, "borrowed_exposure_usd", 0.0) or 0.0) > 0.0
            if _has_margin_exposure and _mg_snap.critical_margin_breach:
                _emit_trade_admission_telemetry(
                    reason="margin_critical",
                    drop_bucket="margin_health",
                    stage="margin_gate",
                )
                return ExecutionDecision(
                    allowed=False,
                    reason=f"margin_critical:{_mg_snap.reason}",
                    circuit_state=configured_circuit_state,
                    state_live_active=state_live_active,
                    lease_valid=lease_valid,
                    lease_generation_current=lease_generation_current,
                    nonce_ready=nonce_ready,
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
                    first_failed_gate="margin.critical_ok",
                    reason_code=_gate_reason_code("margin.critical_ok"),
                    reason_detail=f"margin_critical:{_mg_snap.reason}",
                    lifecycle_phase=current_lifecycle_phase,
                )
            if _has_margin_exposure and not _mg_snap.maintenance_margin_ok:
                # Low margin — block new entries only.  Exit orders (is_reducing)
                # bypass this gate at the adapter level via is_margin_trade_allowed().
                _emit_trade_admission_telemetry(
                    reason="margin_maintenance_low",
                    drop_bucket="margin_health",
                    stage="margin_gate",
                )
                return ExecutionDecision(
                    allowed=False,
                    reason=f"margin_maintenance_low:{_mg_snap.reason}",
                    circuit_state=configured_circuit_state,
                    state_live_active=state_live_active,
                    lease_valid=lease_valid,
                    lease_generation_current=lease_generation_current,
                    nonce_ready=nonce_ready,
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
                    first_failed_gate="margin.maintenance_ok",
                    reason_code=_gate_reason_code("margin.maintenance_ok"),
                    reason_detail=f"margin_maintenance_low:{_mg_snap.reason}",
                    lifecycle_phase=current_lifecycle_phase,
                )
        except Exception as _mg_exc:
            _reason_detail = f"margin_health_gate_unavailable:{_mg_exc}"
            logger.error("Margin health gate unavailable (fail-closed): %s", _mg_exc)
            _emit_trade_admission_telemetry(
                reason="margin_gate_unavailable",
                drop_bucket="margin_health",
                stage="margin_gate",
            )
            return ExecutionDecision(
                allowed=False,
                reason=_reason_detail,
                circuit_state=configured_circuit_state,
                state_live_active=state_live_active,
                lease_valid=lease_valid,
                lease_generation_current=lease_generation_current,
                nonce_ready=nonce_ready,
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
                first_failed_gate="margin.critical_ok",
                reason_code=_gate_reason_code("margin.critical_ok"),
                reason_detail=_reason_detail,
                lifecycle_phase=current_lifecycle_phase,
            )

    return ExecutionDecision(
        allowed=True,
        reason="allowed",
        circuit_state=configured_circuit_state,
        state_live_active=state_live_active,
        lease_valid=lease_valid,
        lease_generation_current=lease_generation_current,
        nonce_ready=nonce_ready,
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
        first_failed_gate="",
        reason_code="allowed",
        reason_detail="allowed",
        lifecycle_phase=current_lifecycle_phase,
    )


def runtime_authority_snapshot() -> RuntimeAuthoritySnapshot:
    """Return runtime convergence status for dispatch-time authority checks.

    Fast path (Fix #5)
    ------------------
    If a recent :class:`~bot.startup_coordinator.GlobalStateSnapshot` is
    available in ``GLOBAL_STATE`` and was built with the same ``trading_state``
    as the current environment, that cached snapshot is reused rather than
    triggering a fresh ``build_snapshot()`` → reconcile cycle.  The staleness
    threshold (2.5 s, matching one scan cycle) ensures the fast path never
    returns a snapshot that is more than one scan cycle stale.
    """
    _SNAPSHOT_FAST_PATH_MAX_AGE_S: float = 2.5
    trading_state_env = os.getenv("NIJA_RUNTIME_TRADING_STATE", "")
    activation_intent = (
        _env_truthy("LIVE_CAPITAL_VERIFIED")
        or _env_truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY")
    )

    # ── Fast path: reuse the most recent GLOBAL_STATE snapshot ───────────────
    try:
        try:
            from bot.startup_coordinator import GLOBAL_STATE
        except ImportError:
            from startup_coordinator import GLOBAL_STATE  # type: ignore[import]

        latest = GLOBAL_STATE.latest()
        if (
            latest is not None
            and (time.monotonic() - latest.snapshot_ts) < _SNAPSHOT_FAST_PATH_MAX_AGE_S
            and latest.startup.trading_state == trading_state_env.strip()
        ):
            _s = latest.startup
            return RuntimeAuthoritySnapshot(
                ready=bool(_s.execution_permitted),
                authority_ready=bool(_s.authority_ready),
                nonce_ready=bool(_s.nonce_ready),
                dispatch_health_ready=bool(_s.dispatch_health_ready),
                dispatch_enabled=bool(_s.dispatch_enabled),
                kill_switch_active=bool(_s.kill_switch_active),
                coordinator_state=str(_s.coordinator_state),
                runtime_state=str(_s.runtime_authority_state),
                reason=str(_s.runtime_authority_reason),
                lifecycle_phase=str(_s.lifecycle_phase),
            )
    except Exception:
        pass  # fall through to slow path

    # ── Slow path: build a fresh snapshot ────────────────────────────────────
    try:
        try:
            from bot.startup_coordinator import get_startup_coordinator
        except ImportError:
            from startup_coordinator import get_startup_coordinator  # type: ignore[import]

        coordinator = get_startup_coordinator()
        snapshot = coordinator.build_snapshot(
            trading_state=trading_state_env,
            activation_intent=activation_intent,
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
            lifecycle_phase=str(snapshot.lifecycle_phase),
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
            lifecycle_phase="BOOT",
        )
