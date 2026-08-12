"""Canonical writer-authority bootstrap for the active Render entrypoint.

The production path is ``main.py -> bot.bot -> bot.bot_main``.  That path must
establish the Redis single-writer lease before any Kraken nonce singleton is
created or inspected.  This module provides that missing ordering contract.

Safety properties
-----------------
* Redis lock acquisition is atomic (Lua + SET under one Redis transaction).
* An active holder is never force-deleted unless its metadata heartbeat is
  detectably stale (age >= NIJA_WRITER_STALE_LOCK_THRESHOLD_S, default 2x TTL).
* Stale-lock reclaim is a compare-and-delete: only the exact stale value read
  before the reclaim is deleted, so a racing live writer is never evicted.
* The process remains fail-closed in standby while Redis/lock authority is
  unavailable.
* Heartbeat renewal verifies exact lock ownership before extending the TTL.
* Release joins the renewal thread before compare-and-delete, so shutdown cannot
  recreate a countdown-only lease after deletion.
* Release is compare-and-delete; a process can never delete another writer's
  lock.
* Local fallback is refused; Redis-backed exact ownership is mandatory.

Structured log events emitted
------------------------------
WRITER_ELECTION_STARTED       – standby loop begins trying to acquire authority
LOCK_ACQUIRED                 – this instance successfully holds the writer lock
HEARTBEAT_RENEWED             – periodic heartbeat successfully extended the lease
STALE_LOCK_DETECTED           – current lock holder's heartbeat is past threshold
FORCED_RECOVERY               – stale lock was evicted; this instance takes over
ACTIVE_WRITER_TRANSITION      – a new writer is now active (emitted on every
                                acquisition, including post-recovery takeovers)
SCAN_STARTED_RECORDED         – trading scan loop emitted its first SCAN_STARTED
SCAN_STARTED_DEADLINE_EXCEEDED – scan did not start within the expected window
"""

from __future__ import annotations

import builtins
import hashlib
import importlib
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum
from types import ModuleType
from typing import Any, Optional

logger = logging.getLogger("nija.entrypoint_writer_authority")

_MARKER = "20260710u"

try:
    from bot.heartbeat_state import (
        WriterLifecyclePhase as _Phase,
        get_heartbeat_state as _get_heartbeat_state,
    )
except ImportError:
    from heartbeat_state import (  # type: ignore[import]
        WriterLifecyclePhase as _Phase,
        get_heartbeat_state as _get_heartbeat_state,
    )
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_GENERATION_KEY_DEFAULT = "nija:lease:generation"


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _cfg_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(os.environ.get(name, str(default)) or default))
    except (TypeError, ValueError):
        return max(minimum, default)


def _cfg_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(float(os.environ.get(name, str(default)) or default)))
    except (TypeError, ValueError):
        return max(minimum, default)


def _live_mode() -> bool:
    return (
        _truthy("LIVE_CAPITAL_VERIFIED")
        and not _truthy("DRY_RUN_MODE")
        and not _truthy("PAPER_MODE")
    )


def _writer_scope() -> str:
    configured = os.environ.get("NIJA_WRITER_LOCK_SCOPE", "").strip()
    if configured:
        return configured
    raw = (
        os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
        or os.environ.get("KRAKEN_API_KEY", "").strip()
        or "default"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _instance_identity() -> tuple[dict[str, str], str, str]:
    try:
        from bot.instance_identity import current_instance_identity, format_instance_identity

        identity = dict(current_instance_identity() or {})
        owner = str(format_instance_identity(identity) or "").strip()
    except Exception:
        identity = {}
        owner = ""

    instance_id = (
        str(identity.get("instance_id") or "").strip()
        or os.environ.get("RENDER_INSTANCE_ID", "").strip()
        or os.environ.get("HOSTNAME", "").strip()
        or f"pid-{os.getpid()}"
    )
    if not owner:
        owner = f"instance={instance_id}|pid={os.getpid()}"
    identity.setdefault("instance_id", instance_id)
    return identity, owner, instance_id


def _connect_redis(timeout_s: float = 3.0):
    try:
        from bot.redis_env import get_redis_url
        from bot.redis_runtime import connect_redis_with_fallback
    except ImportError:
        from redis_env import get_redis_url  # type: ignore[import]
        from redis_runtime import connect_redis_with_fallback  # type: ignore[import]

    redis_url = str(get_redis_url() or "").strip()
    if not redis_url:
        return None, "", "redis_url_missing"

    try:
        client, effective_url = connect_redis_with_fallback(
            url=redis_url,
            decode_responses=True,
            socket_timeout=timeout_s,
            socket_connect_timeout=timeout_s,
            retries=1,
            delay_s=0.0,
            log=lambda msg: logger.debug("entrypoint writer Redis: %s", msg),
        )
        client.ping()
        return client, str(effective_url or redis_url), ""
    except Exception as exc:
        return None, redis_url, f"redis_unavailable:{type(exc).__name__}:{exc}"


@dataclass(frozen=True)
class EntrypointWriterAuthorityResult:
    acquired: bool
    token: str = ""
    generation: int = 0
    instance_id: str = ""
    lock_key: str = ""
    holder: str = ""
    pttl_ms: int = -2
    error: str = ""
    local_fallback: bool = False


class WriterState(str, Enum):
    ACQUIRING = "ACQUIRING"
    VERIFYING = "VERIFYING"
    ACTIVE = "ACTIVE"
    REFRESHING = "REFRESHING"
    LOST = "LOST"


class EntrypointWriterAuthority:
    """Own and maintain the Redis writer lease for ``bot_main``."""

    def __init__(self) -> None:
        self._state_lock = threading.RLock()
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._client: Any = None
        self._result: Optional[EntrypointWriterAuthorityResult] = None
        self._lock_key = ""
        self._meta_key = ""
        self._fencing_key = ""
        self._lock_value = ""
        self._token = ""
        self._generation = 0
        self._ttl_s = 60
        self._identity: dict[str, str] = {}
        self._owner = ""
        self._instance_id = ""
        self._acquired_at = 0.0
        self._local_fallback = False
        self._scan_started_at = 0.0
        self._scan_complete_at: float = 0.0
        # The process writer is acquired before main.py completes its guarded
        # import/handoff phase.  A scan deadline measured from acquisition is
        # therefore not a core-loop deadline.  bot_main explicitly arms this
        # timer immediately before starting the trading engine.
        self._scan_deadline_armed_at = 0.0
        self._scan_deadline_arm_source = ""
        self._scan_deadline_exceeded = False
        self._scan_started_watchdog_thread: Optional[threading.Thread] = None
        self._scan_watchdog_cancel: threading.Event = threading.Event()
        self._core_thread: Optional[threading.Thread] = None
        self._core_thread_started_at = 0.0
        self._core_thread_last_alive_at = 0.0
        self._core_thread_name = ""
        self._core_thread_ident: Optional[int] = None
        # Optional callback invoked by _mark_lost() so callers (e.g. bot_main)
        # can react immediately to lease loss without polling runtime.lost.
        self._on_lost_callback: Optional[Any] = None
        self._writer_state: WriterState = WriterState.ACQUIRING
        self._writer_state_since: float = time.time()
        # Canonical proof of the most recent successful Redis lease operation.
        # The stale-renewal watchdog consumes this value.  Keep it on the
        # authority itself so later runtime patch/canonicalization passes cannot
        # detach proof publication from the actual Redis renewal.
        self._nija_last_lease_renewal_monotonic: float = 0.0
        self._nija_last_lease_renewal_epoch: float = 0.0
        # Readiness reconciliation may perform slow broker I/O. It must never
        # run on the canonical Redis renewal thread or metadata/TTL refreshes
        # can stall behind an exchange timeout. Keep at most one deduplicated
        # reconciliation worker in flight; the heartbeat remains the sole
        # writer-lease renewer.
        self._runtime_reconcile_lock = threading.Lock()
        self._runtime_reconcile_thread: Optional[threading.Thread] = None
        # bot_main normally installs a terminal-loss callback immediately after
        # acquisition.  Pre-bootstrap compatibility paths can acquire earlier,
        # though, and must not become generation-0 zombie processes if core
        # registration later times out.  This timer is the authority owner's
        # final process-lifetime bound for that callback-free path.
        self._unhandled_loss_restart_timer: Optional[threading.Timer] = None
        self._core_recovery_attempts = 0
        self._core_recovery_next_attempt_monotonic = 0.0
        self._terminal_startup_failure_reason = ""
        os.environ["NIJA_WRITER_STATE"] = self._writer_state.value
        os.environ["NIJA_WRITER_STATE_SINCE_TS"] = str(self._writer_state_since)

    @property
    def acquired(self) -> bool:
        return bool(self._result and self._result.acquired and not self._lost.is_set())

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    @property
    def writer_lease_owned(self) -> bool:
        """True when this process holds the exact Redis writer lease.

        Requires:
        - exact Redis lock ownership with matching generation, PID, and fencing token
        - ``lost=False`` (no reelection event detected)
        - writer state is not LOST

        Authorizes: nonce initialization, broker auth, balance reads, position
        reconciliation, held-position adoption, protective exit preparation.
        Does NOT authorize new entries or exposure-increasing orders.
        """
        if self._lost.is_set():
            return False
        if self._writer_state == WriterState.LOST:
            return False
        if not (self._result and self._result.acquired):
            return False
        # Verify fencing token and generation are present (not a local fallback).
        if self._local_fallback:
            return False
        token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()
        generation = os.environ.get("NIJA_WRITER_LEASE_GENERATION", "").strip()
        if not token or not generation:
            return False
        return True

    @property
    def execution_dispatch_authorized(self) -> bool:
        """True when both writer lease is owned AND all dispatch prerequisites are met.

        Additionally requires beyond ``writer_lease_owned``:
        - canonical strategy published (``NIJA_STRATEGY_PUBLISHED=1``)
        - real core thread registered and alive
        - complete readiness proof (all 9 readiness keys)
        - risk systems ready (``NIJA_RISK_SYSTEM_READY=1``)
        - kill switch clear
        - LIVE activation committed (``NIJA_RUNTIME_TRADING_STATE=LIVE_ACTIVE``)
        """
        if not self.writer_lease_owned:
            return False
        # LIVE activation committed
        state = os.environ.get("NIJA_RUNTIME_TRADING_STATE", "").strip().upper()
        if state != "LIVE_ACTIVE":
            return False
        # Core thread registered and alive
        core_registered, core_alive, _ = self._core_thread_status()
        if not (core_registered and core_alive):
            return False
        # Strategy published
        strategy_published = os.environ.get("NIJA_STRATEGY_PUBLISHED", "").strip()
        if strategy_published not in {"1", "true", "yes"}:
            return False
        # Risk systems ready
        risk_ready = os.environ.get("NIJA_RISK_SYSTEM_READY", "").strip()
        if risk_ready not in {"1", "true", "yes"}:
            return False
        # Kill switch must be clear
        kill_switch = os.environ.get("NIJA_KILL_SWITCH_ACTIVE", "").strip()
        if kill_switch in {"1", "true", "yes"}:
            return False
        return True

    @property
    def result(self) -> Optional[EntrypointWriterAuthorityResult]:
        return self._result

    @property
    def writer_state(self) -> WriterState:
        return self._writer_state

    @property
    def terminal_startup_failure_reason(self) -> str:
        return self._terminal_startup_failure_reason

    def mark_terminal_startup_failure(self, reason: str) -> None:
        self._terminal_startup_failure_reason = str(
            reason or "terminal_startup_failure"
        ).strip()

    def _core_thread_status(self) -> tuple[bool, bool, str]:
        thread = self._core_thread
        if thread is None:
            return False, False, "startup_not_registered"
        alive_reader = getattr(thread, "is_alive", None)
        try:
            alive = bool(alive_reader()) if callable(alive_reader) else False
        except Exception:
            alive = False
        if alive:
            return True, True, "ok"
        return (
            True,
            False,
            f"core_thread_dead name={self._core_thread_name or 'unknown'} "
            f"ident={self._core_thread_ident}",
        )

    def _prevent_active_without_registered_core(
        self,
        state: WriterState,
        *,
        reason: str,
    ) -> tuple[WriterState, str]:
        if state != WriterState.ACTIVE:
            return state, reason
        core_registered, core_alive, core_reason = self._core_thread_status()
        if core_registered and core_alive:
            return state, reason
        logger.warning(
            "ACTIVE_WITHOUT_REGISTRATION_PREVENTED marker=%s requested_state=%s "
            "fallback_state=%s reason=%s generation=%s instance_id=%s token_prefix=%s "
            "core_thread_alive=%s core_thread_registered=%s core_thread_reason=%s",
            _MARKER,
            state.value,
            WriterState.VERIFYING.value,
            reason or "unspecified",
            self._generation,
            self._instance_id or "unknown",
            self._token[:8],
            core_alive,
            core_registered,
            core_reason,
        )
        return (
            WriterState.VERIFYING,
            f"active_blocked:{reason or 'unspecified'}:{core_reason}",
        )

    def _recover_core_thread_registration(self, source: str) -> tuple[bool, str]:
        if self._terminal_startup_failure_reason:
            return False, "terminal_startup_failure"
        thread = self._core_thread
        if thread is not None and callable(getattr(thread, "is_alive", None)):
            try:
                if thread.is_alive():
                    return True, "already_registered"
            except Exception:
                pass
        now = time.monotonic()
        if now < self._core_recovery_next_attempt_monotonic:
            wait_s = max(0.0, self._core_recovery_next_attempt_monotonic - now)
            return False, f"recovery_backoff_active wait_s={wait_s:.2f}"
        try:
            try:
                from bot.writer_recovery_epoch_core_v81_patch import (
                    repair_core_thread_once,
                )
            except ImportError:
                from writer_recovery_epoch_core_v81_patch import (  # type: ignore[import]
                    repair_core_thread_once,
                )
        except Exception as exc:
            return False, f"recovery_hook_unavailable:{type(exc).__name__}:{exc}"

        self._core_recovery_attempts += 1
        logger.warning(
            "CORE_THREAD_REGISTRATION_RECOVERY_ATTEMPT marker=%s source=%s "
            "attempt=%d generation=%s instance_id=%s token_prefix=%s",
            _MARKER,
            source,
            self._core_recovery_attempts,
            self._generation,
            self._instance_id or "unknown",
            self._token[:8],
        )
        ok = False
        detail = "unknown"
        try:
            ok, detail = repair_core_thread_once()
        except Exception as exc:
            detail = f"repair_exception:{type(exc).__name__}:{exc}"
        if ok:
            self._core_recovery_attempts = 0
            self._core_recovery_next_attempt_monotonic = 0.0
            logger.critical(
                "CORE_THREAD_REGISTRATION_RECOVERY_SUCCEEDED marker=%s source=%s "
                "generation=%s instance_id=%s token_prefix=%s detail=%s",
                _MARKER,
                source,
                self._generation,
                self._instance_id or "unknown",
                self._token[:8],
                detail,
            )
            return True, str(detail or "recovered")

        base_s = _cfg_float(
            "NIJA_CORE_REGISTRATION_RECOVERY_BASE_S",
            2.0,
            minimum=0.5,
        )
        max_s = _cfg_float(
            "NIJA_CORE_REGISTRATION_RECOVERY_MAX_S",
            30.0,
            minimum=1.0,
        )
        exponential = min(max_s, base_s * (2 ** min(self._core_recovery_attempts - 1, 4)))
        jitter_seed = f"{self._instance_id}:{self._generation}:{self._core_recovery_attempts}"
        jitter_ratio = int(hashlib.sha256(jitter_seed.encode("utf-8")).hexdigest()[:4], 16) / 0xFFFF
        delay_s = min(max_s, exponential + (exponential * 0.25 * jitter_ratio))
        self._core_recovery_next_attempt_monotonic = now + delay_s
        logger.warning(
            "CORE_THREAD_REGISTRATION_RECOVERY_BACKOFF marker=%s source=%s "
            "attempt=%d delay_s=%.2f generation=%s instance_id=%s token_prefix=%s detail=%s",
            _MARKER,
            source,
            self._core_recovery_attempts,
            delay_s,
            self._generation,
            self._instance_id or "unknown",
            self._token[:8],
            detail,
        )
        return False, str(detail or "recovery_failed")

    def _set_writer_state(self, state: WriterState, *, reason: str = "") -> None:
        state, reason = self._prevent_active_without_registered_core(
            state,
            reason=reason,
        )
        with self._state_lock:
            if self._writer_state == state:
                os.environ["NIJA_WRITER_STATE"] = state.value
                os.environ.setdefault(
                    "NIJA_WRITER_STATE_SINCE_TS", str(self._writer_state_since)
                )
                return
            self._writer_state = state
            self._writer_state_since = time.time()
            os.environ["NIJA_WRITER_STATE"] = state.value
            os.environ["NIJA_WRITER_STATE_SINCE_TS"] = str(self._writer_state_since)
        logger.info(
            "WRITER_STATE_TRANSITION marker=%s state=%s reason=%s",
            _MARKER,
            state.value,
            reason or "unspecified",
        )

    def _resolve_loss_grace_s(self) -> float:
        return _cfg_float("NIJA_WRITER_LOSS_GRACE_S", 12.0, minimum=1.0)

    def acquire_with_standby(
        self,
        *,
        shutdown_event: Optional[threading.Event] = None,
    ) -> EntrypointWriterAuthorityResult:
        """Acquire authority before nonce startup, retrying in fail-closed standby.

        ``NIJA_ENTRYPOINT_WRITER_STANDBY_MAX_S=0`` (the default) keeps the
        process alive indefinitely while trading remains blocked.  Set a positive
        value to request a bounded standby window.
        """

        if self._terminal_startup_failure_reason:
            return EntrypointWriterAuthorityResult(
                acquired=False,
                error=f"terminal_startup_failure:{self._terminal_startup_failure_reason}",
            )
        if self.acquired:
            assert self._result is not None
            return self._result

        standby_limit_s = _cfg_float(
            "NIJA_ENTRYPOINT_WRITER_STANDBY_MAX_S", 0.0, minimum=0.0
        )
        retry_s = _cfg_float(
            "NIJA_ENTRYPOINT_WRITER_STANDBY_RETRY_S", 5.0, minimum=0.5
        )
        started = time.monotonic()
        attempt = 0
        last_result = EntrypointWriterAuthorityResult(
            acquired=False,
            error="not_attempted",
        )

        logger.critical(
            "WRITER_ELECTION_STARTED marker=%s standby_limit_s=%.0f retry_s=%.1f pid=%d",
            _MARKER,
            standby_limit_s,
            retry_s,
            os.getpid(),
        )

        while True:
            if shutdown_event is not None and shutdown_event.is_set():
                return EntrypointWriterAuthorityResult(
                    acquired=False,
                    error="shutdown_requested",
                )

            attempt += 1
            last_result = self.acquire_once()
            if last_result.acquired:
                logger.critical(
                    "ENTRYPOINT_WRITER_AUTHORITY_READY marker=%s token_prefix=%s generation=%s "
                    "instance=%s local_fallback=%s",
                    _MARKER,
                    last_result.token[:8],
                    last_result.generation,
                    last_result.instance_id,
                    last_result.local_fallback,
                )
                print(
                    f"[NIJA-PRINT] ENTRYPOINT_WRITER_AUTHORITY_READY marker={_MARKER} "
                    f"generation={last_result.generation} local_fallback={str(last_result.local_fallback).lower()}",
                    flush=True,
                )
                return last_result

            elapsed = time.monotonic() - started
            if standby_limit_s > 0 and elapsed >= standby_limit_s:
                logger.critical(
                    "ENTRYPOINT_WRITER_AUTHORITY_STANDBY_EXHAUSTED marker=%s attempts=%d "
                    "elapsed=%.1fs error=%s holder=%s pttl_ms=%s",
                    _MARKER,
                    attempt,
                    elapsed,
                    last_result.error,
                    last_result.holder,
                    last_result.pttl_ms,
                )
                return last_result

            logger.warning(
                "ENTRYPOINT_WRITER_AUTHORITY_STANDBY marker=%s attempt=%d elapsed=%.1fs "
                "error=%s holder=%s pttl_ms=%s next_retry_s=%.1f",
                _MARKER,
                attempt,
                elapsed,
                last_result.error,
                last_result.holder,
                last_result.pttl_ms,
                retry_s,
            )
            if shutdown_event is not None:
                shutdown_event.wait(retry_s)
            else:
                time.sleep(retry_s)

    def acquire_once(self) -> EntrypointWriterAuthorityResult:
        if self._terminal_startup_failure_reason:
            return EntrypointWriterAuthorityResult(
                acquired=False,
                error=f"terminal_startup_failure:{self._terminal_startup_failure_reason}",
            )
        with self._state_lock:
            self._set_writer_state(WriterState.ACQUIRING, reason="acquire_once")
            if self.acquired:
                assert self._result is not None
                return self._result

            client, _effective_url, connect_error = _connect_redis(
                timeout_s=_cfg_float(
                    "NIJA_ENTRYPOINT_WRITER_REDIS_TIMEOUT_S", 3.0, minimum=0.5
                )
            )
            if client is None:
                fallback = self._maybe_grant_local_fallback(connect_error)
                if fallback is not None:
                    return fallback
                return EntrypointWriterAuthorityResult(
                    acquired=False,
                    error=connect_error or "redis_unavailable",
                )

            identity, owner, instance_id = _instance_identity()
            scope = _writer_scope()
            lock_key = (
                os.environ.get("NIJA_WRITER_LOCK_KEY", "").strip()
                or f"nija:writer_lock:{scope}"
            )
            meta_key = (
                os.environ.get("NIJA_WRITER_LOCK_META_KEY", "").strip()
                or f"nija:writer_lock_meta:{scope}"
            )
            fencing_key = (
                os.environ.get("NIJA_WRITER_FENCING_KEY", "").strip()
                or f"nija:writer_fence:{scope}"
            )
            generation_key = (
                os.environ.get("NIJA_LEASE_GENERATION_KEY", "").strip()
                or _GENERATION_KEY_DEFAULT
            )

            ttl_s = self._resolve_ttl_s()
            wait_s = _cfg_float(
                "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S", 15.0, minimum=0.0
            )
            retry_s = _cfg_float(
                "NIJA_ENTRYPOINT_WRITER_LOCK_RETRY_S", 0.5, minimum=0.1
            )
            stale_threshold_s = _cfg_float(
                "NIJA_WRITER_STALE_LOCK_THRESHOLD_S",
                max(ttl_s * 2.0, 120.0),
                minimum=30.0,
            )
            deadline = time.monotonic() + wait_s
            holder = ""
            pttl_ms = -2

            acquire_script = """
            if redis.call('EXISTS', KEYS[1]) == 1 then
                local holder = redis.call('GET', KEYS[1]) or ''
                local pttl = redis.call('PTTL', KEYS[1]) or -2
                local generation = redis.call('GET', KEYS[3]) or '0'
                return {0, holder, pttl, generation}
            end
            local token = redis.call('INCR', KEYS[2])
            local generation = redis.call('INCR', KEYS[3])
            local value = tostring(token) .. ':' .. ARGV[1]
            redis.call('SET', KEYS[1], value, 'EX', tonumber(ARGV[2]))
            local pttl = redis.call('PTTL', KEYS[1]) or -2
            return {token, value, pttl, generation}
            """

            while True:
                try:
                    raw = client.eval(
                        acquire_script,
                        3,
                        lock_key,
                        fencing_key,
                        generation_key,
                        owner,
                        str(ttl_s),
                    )
                except Exception as exc:
                    return EntrypointWriterAuthorityResult(
                        acquired=False,
                        lock_key=lock_key,
                        error=f"redis_acquire_failed:{type(exc).__name__}:{exc}",
                    )

                token = self._as_int(raw[0] if isinstance(raw, (list, tuple)) and raw else 0)
                holder = self._as_text(raw[1] if isinstance(raw, (list, tuple)) and len(raw) > 1 else "")
                pttl_ms = self._as_int(raw[2] if isinstance(raw, (list, tuple)) and len(raw) > 2 else -2, default=-2)
                generation = self._as_int(raw[3] if isinstance(raw, (list, tuple)) and len(raw) > 3 else 0)

                if token > 0:
                    return self._activate_distributed_authority(
                        client=client,
                        token=str(token),
                        generation=generation,
                        identity=identity,
                        owner=owner,
                        instance_id=instance_id,
                        scope=scope,
                        lock_key=lock_key,
                        meta_key=meta_key,
                        fencing_key=fencing_key,
                        generation_key=generation_key,
                        ttl_s=ttl_s,
                    )

                # Lock is held.  Check whether the holder's heartbeat is stale;
                # if so, forcibly reclaim the lock on behalf of this instance.
                stale, stale_detail = self._check_stale_lock(
                    client, meta_key, holder, stale_threshold_s
                )
                if stale:
                    logger.critical(
                        "STALE_LOCK_DETECTED marker=%s holder=%s "
                        "stale_detail=%s pttl_ms=%s instance=%s",
                        _MARKER,
                        holder,
                        stale_detail,
                        pttl_ms,
                        instance_id,
                    )
                    logger.critical(
                        "WRITER_LOCK_STALE marker=%s holder=%s stale_detail=%s "
                        "pttl_ms=%s contender_instance_id=%s contender_pid=%d",
                        _MARKER,
                        holder,
                        stale_detail,
                        pttl_ms,
                        instance_id,
                        os.getpid(),
                    )
                    reclaimed = self._force_reclaim_stale_lock(
                        client, lock_key, meta_key, holder
                    )
                    if reclaimed:
                        logger.critical(
                            "WRITER_LOCK_RELEASED marker=%s released=true holder=%s "
                            "reason=stale_lock_reclaim",
                            _MARKER,
                            holder,
                        )
                        logger.critical(
                            "FORCED_RECOVERY marker=%s old_holder=%s instance=%s",
                            _MARKER,
                            holder,
                            instance_id,
                        )
                        logger.critical(
                            "WRITER_REELECTION_REQUESTED marker=%s old_holder=%s "
                            "new_instance_id=%s new_pid=%d reason=stale_lock_reclaim",
                            _MARKER,
                            holder,
                            instance_id,
                            os.getpid(),
                        )
                        continue  # Retry acquire immediately after eviction

                if time.monotonic() >= deadline:
                    return EntrypointWriterAuthorityResult(
                        acquired=False,
                        instance_id=instance_id,
                        lock_key=lock_key,
                        holder=holder,
                        pttl_ms=pttl_ms,
                        error="active_writer_lock_held",
                    )
                time.sleep(retry_s)

    def _resolve_ttl_s(self) -> int:
        ttl_raw = os.environ.get("NIJA_WRITER_LOCK_TTL_S", "").strip()
        if ttl_raw:
            return _cfg_int("NIJA_WRITER_LOCK_TTL_S", 60, minimum=15)
        lease_ms = _cfg_int("NIJA_REDIS_LEASE_TTL_MS", 60000, minimum=15000)
        return max(15, int((lease_ms + 999) // 1000))

    def _check_stale_lock(
        self,
        client: Any,
        meta_key: str,
        holder: str,
        threshold_s: float,
    ) -> tuple[bool, str]:
        """Return (is_stale, detail) by inspecting the holder's heartbeat timestamp.

        The check reads the metadata key written by the current lock holder
        during each heartbeat tick.  If the ``heartbeat_at`` field is older
        than *threshold_s* seconds the holder is considered stale (crashed or
        frozen).  A missing or unparseable metadata entry is treated as
        *not* stale to avoid false evictions.
        """
        if not meta_key:
            return False, "no_meta_key"
        try:
            meta_raw = client.get(meta_key)
        except Exception as exc:
            return False, f"meta_read_error:{type(exc).__name__}:{exc}"
        if not meta_raw:
            return False, "no_metadata"
        try:
            meta = json.loads(meta_raw)
        except Exception:
            return False, "meta_parse_error"
        heartbeat_at = float(meta.get("heartbeat_at") or 0)
        if heartbeat_at <= 0:
            return False, "no_heartbeat_ts"
        now = time.time()
        age_s = now - heartbeat_at
        if age_s >= threshold_s:
            return True, f"heartbeat_age={age_s:.1f}s threshold={threshold_s:.1f}s"
        pid = self._as_int(meta.get("pid"), default=0)
        instance_id = self._as_text(meta.get("instance_id"))
        acquired_at = float(meta.get("acquired_at") or 0.0)
        core_alive = bool(meta.get("core_thread_alive", False))
        core_started_at = float(meta.get("core_thread_started_at") or 0.0)
        core_heartbeat_at = float(meta.get("core_thread_heartbeat_at") or 0.0)
        core_grace_s = _cfg_float(
            "NIJA_WRITER_CORE_THREAD_GRACE_S",
            max(threshold_s, 120.0),
            minimum=5.0,
        )
        if core_started_at > 0 and not core_alive:
            return (
                True,
                "core_thread_dead "
                f"instance={instance_id or 'unknown'} pid={pid or 'unknown'} "
                f"core_started_at={core_started_at:.3f}",
            )
        if core_heartbeat_at > 0:
            core_age_s = now - core_heartbeat_at
            if core_age_s >= threshold_s:
                return (
                    True,
                    "core_thread_heartbeat_stale "
                    f"instance={instance_id or 'unknown'} pid={pid or 'unknown'} "
                    f"core_age={core_age_s:.1f}s threshold={threshold_s:.1f}s",
                )
        if acquired_at > 0 and core_started_at <= 0:
            since_acquire_s = now - acquired_at
            if since_acquire_s >= core_grace_s:
                return (
                    True,
                    "core_thread_not_started "
                    f"instance={instance_id or 'unknown'} pid={pid or 'unknown'} "
                    f"age={since_acquire_s:.1f}s grace={core_grace_s:.1f}s",
                )
        return False, f"heartbeat_fresh age={age_s:.1f}s"

    _STALE_RECLAIM_SCRIPT = """
    local current = redis.call('GET', KEYS[1])
    if not current then return 1 end
    if current ~= ARGV[1] then return 0 end
    redis.call('DEL', KEYS[1])
    if KEYS[2] ~= '' then redis.call('DEL', KEYS[2]) end
    return 1
    """

    def _force_reclaim_stale_lock(
        self,
        client: Any,
        lock_key: str,
        meta_key: str,
        old_holder: str,
    ) -> bool:
        """Compare-and-delete the stale lock so only the exact stale value is evicted.

        Returns True when the lock was deleted (or was already gone), False
        when the holder changed between our staleness check and the delete
        (another live writer took over in the interim).
        """
        try:
            result = int(
                client.eval(
                    self._STALE_RECLAIM_SCRIPT,
                    2,
                    lock_key,
                    meta_key or "",
                    old_holder,
                )
                or 0
            )
            return result == 1
        except Exception as exc:
            logger.warning(
                "ENTRYPOINT_WRITER_STALE_RECLAIM_FAILED marker=%s err=%s",
                _MARKER,
                exc,
            )
            return False

    @staticmethod
    def _as_text(value: Any) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value or "")

    @staticmethod
    def _as_int(value: Any, *, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _activate_distributed_authority(
        self,
        *,
        client: Any,
        token: str,
        generation: int,
        identity: dict[str, str],
        owner: str,
        instance_id: str,
        scope: str,
        lock_key: str,
        meta_key: str,
        fencing_key: str,
        generation_key: str,
        ttl_s: int,
    ) -> EntrypointWriterAuthorityResult:
        self._client = client
        self._token = token
        self._generation = generation
        self._identity = identity
        self._owner = owner
        self._instance_id = instance_id
        self._lock_key = lock_key
        self._meta_key = meta_key
        self._fencing_key = fencing_key
        self._lock_value = f"{token}:{owner}"
        self._ttl_s = ttl_s
        self._acquired_at = time.time()
        # Preserve previous confirmed scan-started/complete timestamps across
        # re-acquisitions so the watchdog does not fire SCAN_STARTED_DEADLINE_EXCEEDED
        # when the scan loop is already running (or has already completed).
        _prior_scan_started_at = self._scan_started_at
        _prior_scan_complete_at = self._scan_complete_at
        self._scan_started_at = 0.0
        self._scan_complete_at = 0.0
        self._scan_deadline_armed_at = 0.0
        self._scan_deadline_arm_source = ""
        os.environ.pop("NIJA_SCAN_START_DEADLINE_ARMED_AT", None)
        os.environ.pop("NIJA_SCAN_START_DEADLINE_SOURCE", None)
        self._scan_deadline_exceeded = False
        self._scan_watchdog_cancel.clear()
        self._local_fallback = False
        self._lost.clear()
        self._stop.clear()
        self._terminal_startup_failure_reason = ""
        self._core_recovery_attempts = 0
        self._core_recovery_next_attempt_monotonic = 0.0
        # Preserve a live core thread across re-acquisitions.  Clearing
        # _core_thread on every re-acquisition (e.g. after a transient Redis
        # gap) caused the registration deadline to restart from zero even
        # though the trading thread was still running, eventually triggering an
        # unnecessary re-election and process restart.  If the previously
        # registered thread is still alive we carry it forward and immediately
        # re-arm the scan deadline so the watchdog does not fire.
        _prior_core_thread = self._core_thread
        _prior_core_thread_alive = (
            _prior_core_thread is not None
            and callable(getattr(_prior_core_thread, "is_alive", None))
            and _prior_core_thread.is_alive()
        )
        if _prior_core_thread_alive:
            # Keep all fields; they will be refreshed by register_core_thread
            # below if the caller explicitly re-registers.
            logger.critical(
                "CORE_THREAD_PRESERVED_ACROSS_REACQUISITION marker=%s "
                "thread=%s ident=%s new_generation=%s",
                _MARKER,
                getattr(_prior_core_thread, "name", "unknown"),
                getattr(_prior_core_thread, "ident", None),
                generation,
            )
            os.environ["NIJA_CORE_THREAD_ALIVE"] = "1"
        else:
            self._core_thread = None
            self._core_thread_started_at = 0.0
            self._core_thread_last_alive_at = 0.0
            self._core_thread_name = ""
            self._core_thread_ident = None

        self._publish_env(scope=scope, generation_key=generation_key, fallback=False)
        self._write_metadata()
        self._start_heartbeat()
        self._start_scan_started_watchdog()
        # If the scan was already complete before this re-acquisition, immediately
        # restore that state so the watchdog is cancelled and no false deadline
        # alarms fire while the scan loop is actively running.
        if _prior_scan_complete_at:
            self.record_scan_complete()
        elif _prior_scan_started_at:
            self.record_scan_started()
        self._set_writer_state(WriterState.ACTIVE, reason="lease_acquired")
        self._notify_runtime_reconciliation("writer_acquired")

        logger.critical(
            "LOCK_ACQUIRED marker=%s token_prefix=%s generation=%s instance=%s",
            _MARKER,
            token[:8],
            generation,
            instance_id,
        )
        logger.critical(
            "WRITER_LOCK_ACQUIRED marker=%s token_prefix=%s generation=%s instance_id=%s pid=%d",
            _MARKER,
            token[:8],
            generation,
            instance_id,
            os.getpid(),
        )
        logger.critical(
            "WRITER_ACQUIRED marker=%s token_prefix=%s generation=%s "
            "instance=%s acquired_at=%.3f writer_state=%s",
            _MARKER,
            token[:8],
            generation,
            instance_id,
            self._acquired_at,
            self._writer_state.value,
        )

        result = EntrypointWriterAuthorityResult(
            acquired=True,
            token=token,
            generation=generation,
            instance_id=instance_id,
            lock_key=lock_key,
        )
        self._result = result
        return result

    def _maybe_grant_local_fallback(
        self, reason: str
    ) -> Optional[EntrypointWriterAuthorityResult]:
        if _truthy("NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK"):
            logger.critical(
                "ENTRYPOINT_WRITER_AUTHORITY_LOCAL_FALLBACK_REFUSED marker=%s "
                "reason=%s strict_redis_writer_required=true",
                _MARKER,
                reason,
            )
        return None

    def _record_successful_lease_renewal(self) -> None:
        """Publish proof only after acquisition or exact Redis renewal succeeds."""
        now_epoch = time.time()
        self._nija_last_lease_renewal_monotonic = time.monotonic()
        self._nija_last_lease_renewal_epoch = now_epoch
        os.environ["NIJA_WRITER_LEASE_RENEWAL_ACTIVE"] = "1"
        os.environ["NIJA_WRITER_LEASE_RENEWED_TS"] = f"{now_epoch:.6f}"

    def _nija_lease_renewal_health(self) -> tuple[bool, str, float, float]:
        """Return fail-closed freshness for the canonical renewal proof."""
        if self._local_fallback:
            return False, "local_fallback_forbidden", float("inf"), 0.0
        if not self.acquired:
            return False, "writer_not_acquired", float("inf"), 0.0
        if self.lost:
            return False, "writer_lost", float("inf"), 0.0
        if self._stop.is_set():
            return False, "renewal_stop_requested", float("inf"), 0.0
        thread = self._heartbeat_thread
        if thread is None:
            return False, "renewal_thread_missing", float("inf"), 0.0
        try:
            if not thread.is_alive():
                return False, "renewal_thread_not_alive", float("inf"), 0.0
        except Exception:
            return False, "renewal_thread_state_unavailable", float("inf"), 0.0

        try:
            ttl_s = max(15.0, float(self._ttl_s or 60.0))
        except (TypeError, ValueError):
            ttl_s = 60.0
        raw_interval = str(
            os.environ.get("NIJA_WRITER_HEARTBEAT_INTERVAL_S", "") or ""
        ).strip()
        try:
            interval_s = max(1.0, float(raw_interval)) if raw_interval else min(
                5.0, max(1.0, ttl_s / 3.0)
            )
        except (TypeError, ValueError):
            interval_s = min(5.0, max(1.0, ttl_s / 3.0))
        max_age_s = min(
            max(10.0, interval_s * 3.0),
            max(interval_s * 2.0, ttl_s * 0.75),
        )
        last = float(self._nija_last_lease_renewal_monotonic or 0.0)
        if last <= 0.0:
            return False, "renewal_success_uninitialized", float("inf"), max_age_s
        age_s = max(0.0, time.monotonic() - last)
        if age_s > max_age_s:
            return False, "renewal_success_stale", age_s, max_age_s
        return True, "renewal_healthy", age_s, max_age_s

    def _publish_env(self, *, scope: str, generation_key: str, fallback: bool) -> None:
        now = str(time.time())
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = self._token
        os.environ["NIJA_WRITER_OWNER_ID"] = self._owner
        os.environ["NIJA_WRITER_INSTANCE_ID"] = self._instance_id
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = str(self._generation)
        os.environ["NIJA_WRITER_GENERATION"] = str(self._generation)
        os.environ["NIJA_LEASE_GENERATION_KEY"] = str(generation_key)
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"
        os.environ["NIJA_LOCK_ACQUIRED"] = "true"
        os.environ["NIJA_WRITER_LOCK_KEY"] = self._lock_key
        os.environ["NIJA_WRITER_LOCK_META_KEY"] = self._meta_key
        os.environ["NIJA_WRITER_LOCK_SCOPE"] = scope
        os.environ["NIJA_WRITER_LOCK_TTL_S"] = str(self._ttl_s)
        os.environ["NIJA_WRITER_LOCK_ACQUIRED_AT"] = str(self._acquired_at)
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
        os.environ["NIJA_WRITER_HEARTBEAT_LAST_TS"] = now
        os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = now
        self._record_successful_lease_renewal()
        if fallback:
            os.environ["NIJA_WRITER_FENCING_TOKEN_FALLBACK"] = "1"
            os.environ["NIJA_LOCK_BYPASS_MODE"] = (
                "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK"
            )
        else:
            os.environ.pop("NIJA_WRITER_FENCING_TOKEN_FALLBACK", None)
            os.environ.pop("NIJA_LOCK_BYPASS_MODE", None)
        # Record initial heartbeat and advance lifecycle to LEASE_ACQUIRED.
        try:
            _hs = _get_heartbeat_state()
            _hs.record_heartbeat(generation=self._generation)
            _hs.advance_phase(_Phase.LEASE_ACQUIRED)
        except Exception:
            pass

    def _run_runtime_reconciliation(self, trigger: str) -> None:
        try:
            readiness = importlib.import_module("three_venue_execution_readiness")
            reconcile = getattr(readiness, "reconcile_execution_readiness", None)
            if callable(reconcile):
                reconcile(trigger=trigger, force=True)
        except Exception:
            logger.debug(
                "ENTRYPOINT_WRITER_RUNTIME_RECONCILIATION_DEFERRED marker=%s trigger=%s",
                _MARKER,
                trigger,
                exc_info=True,
            )

    def _notify_runtime_reconciliation(self, trigger: str) -> None:
        """Notify readiness without allowing broker I/O to stall lease renewal."""
        if trigger != "heartbeat_renewed":
            self._run_runtime_reconciliation(trigger)
            return

        with self._runtime_reconcile_lock:
            worker = self._runtime_reconcile_thread
            if worker is not None and worker.is_alive():
                return

            def _worker() -> None:
                try:
                    self._run_runtime_reconciliation(trigger)
                finally:
                    with self._runtime_reconcile_lock:
                        if self._runtime_reconcile_thread is threading.current_thread():
                            self._runtime_reconcile_thread = None

            worker = threading.Thread(
                target=_worker,
                name="writer-readiness-reconciliation",
                daemon=True,
            )
            self._runtime_reconcile_thread = worker
            worker.start()

    def _metadata_payload(self) -> str:
        core_alive = False
        core_heartbeat_at = self._core_thread_last_alive_at or 0.0
        thread = self._core_thread
        if thread is not None and callable(getattr(thread, "is_alive", None)):
            try:
                core_alive = bool(thread.is_alive())
                if core_alive:
                    core_heartbeat_at = time.time()
                    self._core_thread_last_alive_at = core_heartbeat_at
            except Exception:
                core_alive = False
        return json.dumps(
            {
                "token": self._token,
                "instance": self._identity,
                "instance_id": self._instance_id,
                "pid": os.getpid(),
                "generation": self._generation,
                "acquired_at": self._acquired_at,
                "heartbeat_at": time.time(),
                "core_thread_name": self._core_thread_name,
                "core_thread_ident": self._core_thread_ident,
                "core_thread_started_at": self._core_thread_started_at,
                "core_thread_alive": core_alive,
                "core_thread_heartbeat_at": core_heartbeat_at,
                "lock_ttl_s": self._ttl_s,
                "source": "entrypoint_writer_authority",
            },
            sort_keys=True,
        )

    def register_core_thread(self, thread: Optional[threading.Thread]) -> None:
        """Register the core trading thread so lock metadata can expose liveness."""
        if thread is None:
            return
        self.arm_scan_start_deadline("core_thread_registered")
        self._core_thread = thread
        self._core_thread_name = str(getattr(thread, "name", "") or "")
        self._core_thread_ident = getattr(thread, "ident", None)
        now = time.time()
        self._core_thread_started_at = now
        self._core_thread_last_alive_at = now if thread.is_alive() else 0.0
        self._core_recovery_attempts = 0
        self._core_recovery_next_attempt_monotonic = 0.0
        os.environ["NIJA_CORE_THREAD_ALIVE"] = "1" if thread.is_alive() else "0"
        self._scan_deadline_exceeded = False
        self._write_metadata()
        self._set_writer_state(WriterState.ACTIVE, reason="core_thread_registered")
        self._notify_runtime_reconciliation("core_thread_registered")

    def arm_scan_start_deadline(self, source: str = "runtime_handoff") -> None:
        """Arm the scan-start watchdog when the trading engine is expected.

        Writer acquisition intentionally precedes guarded runtime imports.  The
        startup scan deadline must begin at the actual engine handoff, not while
        the process is still installing fail-closed controls.
        """
        if self._scan_started_at or self._scan_complete_at:
            return
        with self._state_lock:
            if self._scan_deadline_armed_at:
                return
            self._scan_deadline_armed_at = time.time()
            self._scan_deadline_arm_source = str(source or "runtime_handoff")
            os.environ["NIJA_SCAN_START_DEADLINE_ARMED_AT"] = str(
                self._scan_deadline_armed_at
            )
            os.environ["NIJA_SCAN_START_DEADLINE_SOURCE"] = (
                self._scan_deadline_arm_source
            )
        logger.critical(
            "SCAN_START_DEADLINE_ARMED marker=%s source=%s instance=%s generation=%s",
            _MARKER,
            self._scan_deadline_arm_source,
            self._instance_id,
            self._generation,
        )
        self._start_scan_started_watchdog()

    def _write_metadata(self) -> None:
        if self._client is None or not self._meta_key:
            return
        try:
            self._client.set(
                self._meta_key,
                self._metadata_payload(),
                ex=max(15, self._ttl_s),
            )
        except Exception as exc:
            logger.warning(
                "ENTRYPOINT_WRITER_AUTHORITY_METADATA_WRITE_FAILED marker=%s err=%s",
                _MARKER,
                exc,
            )

    def _start_heartbeat(self) -> None:
        if self._local_fallback:
            return
        if self._heartbeat_thread is not None and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="entrypoint-writer-lock-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def record_scan_started(self) -> None:
        """Record that the trading scan loop has emitted its first SCAN_STARTED.

        Call this immediately after the scan loop emits ``SCAN_STARTED`` so
        the startup-window watchdog can confirm timely scan commencement.
        Idempotent — only the first call is recorded.
        """
        if self._scan_started_at:
            return
        if not self._scan_deadline_armed_at:
            self.arm_scan_start_deadline("scan_started")
        self._scan_started_at = time.time()
        # Clear the deadline flag so _validate_core_thread_liveness and the
        # watchdog loop no longer treat an exceeded startup window as an error.
        # The scan deadline is a startup-only timeout; it must never fire after
        # initialization completes.
        self._scan_deadline_exceeded = False
        elapsed = self._scan_started_at - self._acquired_at if self._acquired_at else 0.0
        logger.info(
            "SCAN_STARTED_RECORDED marker=%s elapsed_since_acquisition=%.1fs "
            "instance=%s generation=%s",
            _MARKER,
            elapsed,
            self._instance_id,
            self._generation,
        )
        # Advance lifecycle phase
        try:
            _get_heartbeat_state().advance_phase(_Phase.SCAN_RUNNING)
        except Exception:
            pass

    def record_scan_complete(self) -> None:
        """Record that the first full trading scan has completed.

        Call this once the initial market-scan pass finishes so the
        startup-only watchdog deadline is permanently retired and the
        lifecycle advances to ``SCAN_COMPLETE``.  Idempotent — only the
        first call is recorded.  Calling this without a prior call to
        :meth:`record_scan_started` implicitly records scan-started first.
        """
        if not self._scan_started_at:
            # Ensure scan-started is recorded before marking it complete.
            self.record_scan_started()
        if self._scan_complete_at:
            return
        self._scan_complete_at = time.time()
        self._scan_deadline_exceeded = False
        elapsed = self._scan_complete_at - self._acquired_at if self._acquired_at else 0.0
        logger.info(
            "SCAN_COMPLETE_RECORDED marker=%s elapsed_since_acquisition=%.1fs "
            "instance=%s generation=%s",
            _MARKER,
            elapsed,
            self._instance_id,
            self._generation,
        )
        # Cancel the startup watchdog — the scan deadline is now permanently
        # retired and the watchdog thread must not fire SCAN_STARTED_DEADLINE_EXCEEDED
        # after a successful first scan.
        self._scan_watchdog_cancel.set()
        try:
            _get_heartbeat_state().advance_phase(_Phase.SCAN_COMPLETE)
        except Exception:
            pass

    def _start_scan_started_watchdog(self) -> None:
        """Start a daemon thread that warns if SCAN_STARTED is not recorded in time."""
        if self._scan_started_watchdog_thread is not None and \
                self._scan_started_watchdog_thread.is_alive():
            return
        self._scan_watchdog_cancel.clear()
        deadline_s = _cfg_float("NIJA_SCAN_STARTED_DEADLINE_S", 300.0, minimum=30.0)
        t = threading.Thread(
            target=self._scan_started_watchdog_loop,
            args=(deadline_s,),
            name="entrypoint-scan-started-watchdog",
            daemon=True,
        )
        t.start()
        self._scan_started_watchdog_thread = t

    def _scan_started_watchdog_loop(self, deadline_s: float) -> None:
        poll_interval = min(10.0, max(1.0, deadline_s / 10.0))
        _deadline_last_logged = 0.0
        _deadline_rewarning_s = min(60.0, max(poll_interval, deadline_s / 5.0))
        # Use a do-while pattern: perform the check on each iteration *before*
        # waiting, so that setting _stop prior to the first iteration still
        # allows the deadline flag to be evaluated at least once.
        while True:
            if (
                not self.acquired
                or self._scan_started_at
                or self._scan_complete_at
                or self._scan_watchdog_cancel.is_set()
            ):
                # Scan started (or was explicitly cancelled after completion) —
                # clear any previously set deadline flag and exit.  This handles
                # the case where record_scan_started() was called after the
                # deadline had already been exceeded.
                self._scan_deadline_exceeded = False
                return  # Scan started; watchdog duty fulfilled
            armed_at = self._scan_deadline_armed_at
            if armed_at <= 0.0:
                if self._stop.is_set():
                    return
                if self._scan_watchdog_cancel.wait(timeout=poll_interval):
                    self._scan_deadline_exceeded = False
                    return
                continue
            elapsed = time.time() - armed_at
            if elapsed >= deadline_s:
                self._scan_deadline_exceeded = True
                now = time.time()
                if now - _deadline_last_logged >= _deadline_rewarning_s:
                    _deadline_last_logged = now
                    logger.error(
                        "SCAN_STARTED_DEADLINE_EXCEEDED marker=%s deadline_s=%.0f "
                        "elapsed_since_deadline_arm=%.1fs elapsed_since_acquisition=%.1fs "
                        "arm_source=%s writer_acquired=%s instance=%s",
                        _MARKER,
                        deadline_s,
                        elapsed,
                        time.time() - (self._acquired_at or time.time()),
                        self._scan_deadline_arm_source or "unknown",
                        self.acquired,
                        self._instance_id,
                    )
                # Do not release the writer lease or trigger re-election.
                # The scan may still start once exchange connections finish
                # bootstrapping.  Keep monitoring until scan starts or the
                # authority is stopped externally.
                if self._stop.is_set():
                    return
                if self._scan_watchdog_cancel.wait(timeout=poll_interval):
                    self._scan_deadline_exceeded = False
                    return
                continue
            if self._stop.is_set():
                return
            remaining = (armed_at + deadline_s) - time.time()
            if self._scan_watchdog_cancel.wait(timeout=min(poll_interval, max(0.1, remaining))):
                self._scan_deadline_exceeded = False
                return

    def _heartbeat_loop(self) -> None:
        interval_s = _cfg_float(
            "NIJA_WRITER_HEARTBEAT_INTERVAL_S",
            min(5.0, max(1.0, self._ttl_s / 3.0)),
            minimum=1.0,
        )
        grace_s = self._resolve_loss_grace_s()
        failures = 0
        first_failure_at = 0.0

        while not self._stop.is_set():
            ok, reason = self._heartbeat_tick()
            if ok:
                failures = 0
                first_failure_at = 0.0
                self._set_writer_state(WriterState.ACTIVE, reason="heartbeat_ok")
            else:
                try:
                    _get_heartbeat_state().record_heartbeat_failure()
                except Exception:
                    pass
                failures += 1
                now = time.time()
                if first_failure_at <= 0.0:
                    first_failure_at = now
                elapsed = max(0.0, now - first_failure_at)
                ownership_lost = reason in {
                    "lock_owned_by_different_writer",
                    "lock_missing_and_fencing_token_mismatch",
                }
                if ownership_lost:
                    self._set_writer_state(
                        WriterState.LOST,
                        reason=f"ownership_lost:{reason}",
                    )
                    self._mark_lost(reason)
                    return
                self._set_writer_state(
                    WriterState.REFRESHING,
                    reason=f"heartbeat_failure:{reason}",
                )
                logger.warning(
                    "ENTRYPOINT_WRITER_HEARTBEAT_FAILED marker=%s failures=%d grace_s=%.1f "
                    "elapsed_s=%.1f reason=%s",
                    _MARKER,
                    failures,
                    grace_s,
                    elapsed,
                    reason,
                )
                if elapsed >= grace_s:
                    self._set_writer_state(
                        WriterState.LOST,
                        reason=f"heartbeat_grace_expired:{reason}",
                    )
                    self._mark_lost(f"heartbeat_grace_expired:{reason}")
                    return
            self._stop.wait(interval_s)

    def _check_authority_invariant(self) -> tuple[bool, str]:
        """Enforce the authority invariant before each lease renewal.

        The invariant is:

            lease_acquired == (fencing_token_active AND heartbeat_running AND core_ok)

        Two asymmetric violations are actionable:

        * ``NIJA_WRITER_LEASE_ACQUIRED == "1"`` but ``NIJA_WRITER_FENCING_TOKEN``
          is absent — the token was externally cleared while the lease flag was
          not.  Release immediately so execution gates never operate in a
          half-initialized state.

        * ``self.acquired`` is True (in-memory) but ``NIJA_WRITER_LEASE_ACQUIRED``
          has been set to a non-truthy value by an external initialisation path
          (e.g. ``render_startup_convergence_patch.normalize_derived_runtime_state``
          running before it checked the singleton).  Release immediately so the
          in-memory state converges with the environment.

        Returns (ok, reason).  ok==False means the caller should stop the
        heartbeat; the release has already been initiated here.
        """
        _truthy = {"1", "true", "yes", "on", "enabled"}
        lease_flag = os.environ.get("NIJA_WRITER_LEASE_ACQUIRED", "").strip()
        lease_set = lease_flag in _truthy
        token = os.environ.get("NIJA_WRITER_FENCING_TOKEN", "").strip()

        # Violation 1: env says lease held but fencing token is gone.
        if lease_set and not token:
            reason = (
                "authority_invariant_violated:lease_acquired_but_fencing_token_missing "
                f"NIJA_WRITER_LEASE_ACQUIRED={lease_flag!r}"
            )
            logger.critical(
                "WRITER_AUTHORITY_INVARIANT_VIOLATED marker=%s %s",
                _MARKER,
                reason,
            )
            self._release_owned_lock_for_reelection(reason)
            return False, reason

        # Violation 2: in-memory singleton says acquired but env was externally
        # cleared to a falsy value.
        if self.acquired and lease_flag and not lease_set:
            reason = (
                "authority_invariant_violated:singleton_acquired_but_env_cleared "
                f"NIJA_WRITER_LEASE_ACQUIRED={lease_flag!r}"
            )
            logger.critical(
                "WRITER_AUTHORITY_INVARIANT_VIOLATED marker=%s %s",
                _MARKER,
                reason,
            )
            self._release_owned_lock_for_reelection(reason)
            return False, reason

        return True, ""

    def _heartbeat_tick(self) -> tuple[bool, str]:
        os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = str(time.time())
        self._set_writer_state(WriterState.VERIFYING, reason="heartbeat_tick")

        # Enforce the authority invariant before each renewal.  If the fencing
        # token has been externally cleared or the lease flag was externally
        # reset, release authority immediately rather than renewing a lease in
        # a partial state.
        inv_ok, inv_reason = self._check_authority_invariant()
        if not inv_ok:
            return False, inv_reason

        core_ok, core_reason = self._validate_core_thread_liveness()
        core_registered = self._core_thread is not None
        core_alive = bool(core_registered and core_ok)
        # Publish liveness state so the authority heartbeat monitor can also
        # gate on core_thread_alive (Fix 2).
        os.environ["NIJA_CORE_THREAD_ALIVE"] = "1" if core_alive else "0"
        if not core_ok:
            self._release_owned_lock_for_reelection(core_reason)
            return False, core_reason
        if self._client is None:
            return False, "redis_client_missing"

        script = """
        local current = redis.call('GET', KEYS[1])
        if not current then
            local fence = ''
            if KEYS[3] and KEYS[3] ~= '' then
                fence = tostring(redis.call('GET', KEYS[3]) or '')
            end
            if fence ~= '' and fence == tostring(ARGV[4]) then
                redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
                if KEYS[2] and KEYS[2] ~= '' then
                    redis.call('SET', KEYS[2], ARGV[3], 'EX', tonumber(ARGV[2]))
                end
                return 2
            end
            return -1
        end
        if current ~= ARGV[1] then return 0 end
        redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
        if KEYS[2] and KEYS[2] ~= '' then
            redis.call('SET', KEYS[2], ARGV[3], 'EX', tonumber(ARGV[2]))
        end
        return 1
        """
        try:
            code = int(
                self._client.eval(
                    script,
                    3,
                    self._lock_key,
                    self._meta_key,
                    self._fencing_key,
                    self._lock_value,
                    str(self._ttl_s),
                    self._metadata_payload(),
                    self._token,
                )
                or 0
            )
            if code in {1, 2}:
                now = str(time.time())
                os.environ["NIJA_WRITER_HEARTBEAT_LAST_TS"] = now
                os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = now
                os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
                self._record_successful_lease_renewal()
                try:
                    _get_heartbeat_state().record_heartbeat(generation=self._generation)
                except Exception:
                    pass
                logger.debug(
                    "HEARTBEAT_RENEWED marker=%s token_prefix=%s generation=%s",
                    _MARKER,
                    self._token[:8],
                    self._generation,
                )
                logger.info(
                    "WRITER_LOCK_RENEWED marker=%s token_prefix=%s generation=%s "
                    "instance_id=%s pid=%d core_thread_alive=%s "
                    "core_thread_registered=%s core_thread_reason=%s",
                    _MARKER,
                    self._token[:8],
                    self._generation,
                    self._instance_id,
                    os.getpid(),
                    core_alive,
                    core_registered,
                    core_reason or ("ok" if core_registered else "startup_not_registered"),
                )
                if code == 2:
                    logger.warning(
                        "WRITER_LOCK_REFRESHED_FROM_FENCING marker=%s token_prefix=%s",
                        _MARKER,
                        self._token[:8],
                    )
                self._set_writer_state(WriterState.ACTIVE, reason="heartbeat_renewed")
                self._notify_runtime_reconciliation("heartbeat_renewed")
                return True, ""
            if code == -1:
                return False, "lock_missing_and_fencing_token_mismatch"
            return False, "lock_owned_by_different_writer"
        except Exception as exc:
            return False, f"redis_heartbeat_error:{type(exc).__name__}:{exc}"

    def _validate_core_thread_liveness(self) -> tuple[bool, str]:
        """Ensure the lock owner is actively running the core trading thread.

        A missing core thread is allowed only for a bounded startup window.
        The bound is measured from writer acquisition, independently of the
        later scan-start deadline, so a startup that never reaches the engine
        handoff cannot renew the writer lease forever.  Once the bound expires
        the heartbeat releases the exact owned lease and bot_main schedules a
        controlled non-zero process restart.

        Exception: if the scan-started deadline has already been exceeded AND
        the scan has not yet started (i.e. _scan_started_at is still zero) the
        core loop is considered permanently stalled and (False, reason) is
        returned so the heartbeat stops renewing the lease.  Once the scan has
        started (or the lifecycle phase has advanced past LEASE_ACQUIRED),
        the deadline is no longer relevant and this check remains healthy for
        an unregistered startup thread while reporting that state truthfully.
        """
        if self._local_fallback:
            return False, "core_thread_local_fallback_forbidden"
        thread = self._core_thread
        if thread is None:
            recovery_ok, recovery_reason = self._recover_core_thread_registration(
                "startup_not_registered"
            )
            if recovery_ok:
                thread = self._core_thread
                if thread is not None and callable(getattr(thread, "is_alive", None)):
                    try:
                        if thread.is_alive():
                            self._core_thread_last_alive_at = time.time()
                            return True, recovery_reason
                    except Exception:
                        pass
            registration_deadline_s = _cfg_float(
                "NIJA_CORE_REGISTRATION_DEADLINE_S",
                600.0,
                minimum=60.0,
            )
            if self._acquired_at > 0.0:
                elapsed_s = max(0.0, time.time() - self._acquired_at)
                if elapsed_s >= registration_deadline_s:
                    reason = (
                        "core_thread_missing core_thread_registration_deadline_exceeded "
                        f"elapsed_s={elapsed_s:.1f} "
                        f"deadline_s={registration_deadline_s:.1f}"
                    )
                    logger.critical(
                        "CANONICAL_CORE_REGISTRATION_DEADLINE_EXCEEDED marker=%s "
                        "elapsed_s=%.1f deadline_s=%.1f instance=%s generation=%s "
                        "action=release_writer_and_restart",
                        _MARKER,
                        elapsed_s,
                        registration_deadline_s,
                        self._instance_id,
                        self._generation,
                    )
                    self.mark_terminal_startup_failure(reason)
                    return False, reason

            # The engine handoff has its own shorter scan-start deadline.  It
            # remains authoritative once armed, but it can no longer be the
            # only bound on pre-handoff startup.
            if self._scan_deadline_exceeded and not self._scan_started_at:
                return False, "core_thread_missing_deadline_exceeded"
            return True, ""
        if not thread.is_alive():
            return (
                False,
                f"core_thread_dead name={self._core_thread_name or 'unknown'} "
                f"ident={self._core_thread_ident}",
            )
        self._core_thread_last_alive_at = time.time()
        return True, ""

    def _release_owned_lock_for_reelection(self, reason: str) -> None:
        """Release this instance's lock when local writer runtime is stale/dead."""
        released = False
        terminal_failure = bool(
            self._terminal_startup_failure_reason
            or "registration_deadline_exceeded" in str(reason or "")
        )
        if terminal_failure and not self._terminal_startup_failure_reason:
            self.mark_terminal_startup_failure(reason)
        self._stop.set()
        if reason.startswith("core_thread_"):
            logger.critical(
                "CORE_THREAD_DIED marker=%s instance_id=%s pid=%d reason=%s",
                _MARKER,
                self._instance_id,
                os.getpid(),
                reason,
            )
        if self._client is not None and self._lock_key and self._lock_value:
            script = """
            local current = redis.call('GET', KEYS[1])
            if not current or current ~= ARGV[1] then return 0 end
            redis.call('DEL', KEYS[1])
            if KEYS[2] and KEYS[2] ~= '' then redis.call('DEL', KEYS[2]) end
            return 1
            """
            try:
                released = bool(
                    int(
                        self._client.eval(
                            script,
                            2,
                            self._lock_key,
                            self._meta_key,
                            self._lock_value,
                        )
                        or 0
                    )
                )
            except Exception as exc:
                logger.warning(
                    "WRITER_LOCK_RELEASE_FAILED marker=%s err=%s reason=%s",
                    _MARKER,
                    exc,
                    reason,
                )
        logger.critical(
            "WRITER_LOCK_RELEASED marker=%s released=%s instance_id=%s pid=%d reason=%s",
            _MARKER,
            released,
            self._instance_id,
            os.getpid(),
            reason,
        )
        logger.critical(
            "WRITER_REELECTION_REQUESTED marker=%s trigger_instance_id=%s pid=%d "
            "reason=%s terminal_startup_failure=%s",
            _MARKER,
            self._instance_id,
            os.getpid(),
            reason,
            terminal_failure,
        )
        loss_reason_prefix = (
            "writer_lock_released_for_terminal_shutdown"
            if terminal_failure
            else "writer_lock_released_for_reelection"
        )
        self._mark_lost(f"{loss_reason_prefix}:{reason}")

    def set_on_lost_callback(self, callback: Any) -> None:
        """Register a callable invoked synchronously when the lease is lost.

        The callback is called with a single positional argument: the reason
        string.  It is invoked inside ``_mark_lost()`` on the heartbeat thread,
        so it must be lightweight (e.g. ``event.set()``).  Returning a truthy
        value confirms that the callback installed its own bounded process
        restart; false/``None`` leaves the runtime fallback responsible.
        """
        self._on_lost_callback = callback

    def _schedule_unhandled_loss_restart(
        self,
        reason: str,
        *,
        handler_confirmed: bool = False,
    ) -> None:
        """Bound a live writer process unless a callback confirmed handoff.

        The Redis lease is already released before this method is reached.
        Restarting cannot grant authority; it only prevents a callback-free
        or stale-callback bootstrap process from continuing broker/readiness
        monitors forever with generation zero.
        """

        if not _live_mode() or handler_confirmed:
            return
        # Only a runtime that actually started the canonical renewal worker can
        # become the production zombie this guard targets.  This also keeps
        # isolated proof objects and direct unit-test helpers side-effect free.
        heartbeat = self._heartbeat_thread
        if heartbeat is None or not heartbeat.is_alive():
            return
        timer = self._unhandled_loss_restart_timer
        if timer is not None and timer.is_alive():
            return
        grace_s = _cfg_float(
            "NIJA_WRITER_AUTHORITY_FALLBACK_RESTART_GRACE_S",
            _cfg_float(
                "NIJA_WRITER_AUTHORITY_RESTART_GRACE_S",
                _cfg_float("NIJA_CORE_REGISTRATION_RESTART_GRACE_S", 15.0, minimum=1.0),
                minimum=1.0,
            ),
            minimum=1.0,
        )

        def _force_restart() -> None:
            logger.critical(
                "ENTRYPOINT_WRITER_AUTHORITY_FALLBACK_RESTART marker=%s "
                "reason=%s exit_code=75 callback_handoff_confirmed=false",
                _MARKER,
                reason,
            )
            for handler in logging.getLogger().handlers:
                try:
                    handler.flush()
                except Exception:
                    pass
            os._exit(75)

        timer = threading.Timer(grace_s, _force_restart)
        timer.name = "entrypoint-writer-unhandled-loss-restart"
        timer.daemon = True
        self._unhandled_loss_restart_timer = timer
        logger.critical(
            "ENTRYPOINT_WRITER_AUTHORITY_FALLBACK_RESTART_SCHEDULED marker=%s "
            "reason=%s grace_s=%.1f callback_handoff_confirmed=false",
            _MARKER,
            reason,
            grace_s,
        )
        timer.start()

    def _mark_lost(self, reason: str) -> None:
        self._set_writer_state(WriterState.LOST, reason=reason)
        self._lost.set()
        try:
            _get_heartbeat_state().reset()
        except Exception:
            pass
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
        # Pop rather than set-to-0: once the lease is lost,
        # NIJA_WRITER_LEASE_ACQUIRED=0 is the authoritative signal.
        # Leaving NIJA_CORE_THREAD_ALIVE=0 in the environment would
        # cascade across subsequent test setUp/tearDown cycles.
        os.environ.pop("NIJA_CORE_THREAD_ALIVE", None)
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
        os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
        os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)
        os.environ.pop("NIJA_WRITER_GENERATION", None)
        os.environ.pop("NIJA_WRITER_LEASE_GENERATION", None)
        try:
            from bot.readiness_table import revoke_many

            revoke_many(
                ("authority_ready", "nonce_ready", "execution_ready"),
                reason=f"writer_authority_lost:{reason}",
            )
        except Exception:
            logger.debug(
                "ENTRYPOINT_WRITER_AUTHORITY_READINESS_REVOKE_FAILED marker=%s",
                _MARKER,
                exc_info=True,
            )
        logger.critical(
            "ENTRYPOINT_WRITER_AUTHORITY_LOST marker=%s reason=%s",
            _MARKER,
            reason,
        )
        self._notify_runtime_reconciliation("writer_lost")
        callback = self._on_lost_callback
        callback_handled = False
        if callback is not None:
            try:
                callback_handled = bool(callback(reason))
            except Exception as cb_exc:
                logger.error(
                    "ENTRYPOINT_WRITER_AUTHORITY_LOST_CALLBACK_FAILED marker=%s err=%s",
                    _MARKER,
                    cb_exc,
                )
        logger.critical(
            "ENTRYPOINT_WRITER_AUTHORITY_LOST_CALLBACK_HANDOFF marker=%s "
            "callback_present=%s restart_confirmed=%s",
            _MARKER,
            callback is not None,
            callback_handled,
        )
        self._schedule_unhandled_loss_restart(
            reason,
            handler_confirmed=callback_handled,
        )
        try:
            from bot.single_execution_authority_kernel import get_seak

            get_seak().emergency_halt(f"entrypoint_writer_authority_lost:{reason}")
        except Exception as exc:
            logger.error(
                "ENTRYPOINT_WRITER_AUTHORITY_SEAK_HALT_FAILED marker=%s err=%s",
                _MARKER,
                exc,
            )

    def release(self) -> bool:
        """Quiesce heartbeat, then compare-delete only this process's lock."""

        self._stop.set()
        self._set_writer_state(WriterState.LOST, reason="release_called")
        try:
            from bot.readiness_table import revoke_many

            revoke_many(
                ("authority_ready", "nonce_ready", "execution_ready"),
                reason="writer_authority_release_called",
            )
        except Exception:
            logger.debug(
                "ENTRYPOINT_WRITER_AUTHORITY_READINESS_REVOKE_FAILED marker=%s",
                _MARKER,
                exc_info=True,
            )
        heartbeat = self._heartbeat_thread
        if heartbeat is not None and heartbeat is not threading.current_thread():
            if heartbeat.is_alive():
                heartbeat.join(
                    timeout=_cfg_float(
                        "NIJA_WRITER_RELEASE_HEARTBEAT_JOIN_S",
                        2.0,
                        minimum=0.1,
                    )
                )
            if heartbeat.is_alive():
                logger.critical(
                    "ENTRYPOINT_WRITER_AUTHORITY_RELEASE_HEARTBEAT_TIMEOUT marker=%s "
                    "reason=heartbeat_thread_still_alive_after_join "
                    "deletion_skipped=true stop_already_set=true",
                    _MARKER,
                )
                # Never delete a lease while its renewal thread may still be in
                # flight.  Revoke local authority immediately and leave the
                # Redis key to its TTL (or a later release after quiescence).
                with self._state_lock:
                    os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"
                    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
                    os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = "0"
                    os.environ.pop("NIJA_CORE_THREAD_ALIVE", None)
                    os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)
                    os.environ.pop("NIJA_WRITER_GENERATION", None)
                    os.environ.pop("NIJA_WRITER_FENCING_TOKEN_FALLBACK", None)
                    os.environ.pop("NIJA_WRITER_LEASE_GENERATION", None)
                self._notify_runtime_reconciliation("writer_release_heartbeat_not_quiesced")
                return False

        with self._state_lock:
            released = False
            if self._client is not None and self._lock_key and self._lock_value:
                script = """
                local current = redis.call('GET', KEYS[1])
                if not current or current ~= ARGV[1] then return 0 end
                redis.call('DEL', KEYS[1])
                if KEYS[2] and KEYS[2] ~= '' then redis.call('DEL', KEYS[2]) end
                return 1
                """
                try:
                    released = bool(
                        int(
                            self._client.eval(
                                script,
                                2,
                                self._lock_key,
                                self._meta_key,
                                self._lock_value,
                            )
                            or 0
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        "ENTRYPOINT_WRITER_AUTHORITY_RELEASE_FAILED marker=%s err=%s",
                        _MARKER,
                        exc,
                    )

            self._heartbeat_thread = None
            try:
                _get_heartbeat_state().reset()
            except Exception:
                pass
            os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"
            os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
            os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = "0"
            # Pop rather than set-to-0: NIJA_WRITER_LEASE_ACQUIRED=0 is the
            # authoritative signal once the lease is explicitly released.
            os.environ.pop("NIJA_CORE_THREAD_ALIVE", None)
            os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)
            os.environ.pop("NIJA_WRITER_GENERATION", None)
            os.environ.pop("NIJA_WRITER_FENCING_TOKEN_FALLBACK", None)
            os.environ.pop("NIJA_WRITER_LEASE_GENERATION", None)
            os.environ.pop("NIJA_SCAN_START_DEADLINE_ARMED_AT", None)
            os.environ.pop("NIJA_SCAN_START_DEADLINE_SOURCE", None)
            logger.info(
                "ENTRYPOINT_WRITER_AUTHORITY_RELEASED marker=%s released=%s "
                "local_fallback=%s heartbeat_quiesced=true",
                _MARKER,
                released,
                self._local_fallback,
            )
            logger.critical(
                "WRITER_LOCK_RELEASED marker=%s released=%s local_fallback=%s "
                "instance_id=%s pid=%d reason=release_called",
                _MARKER,
                released,
                self._local_fallback,
                self._instance_id,
                os.getpid(),
            )
            self._notify_runtime_reconciliation("writer_released")
            return released or self._local_fallback


_SINGLETON: Optional[EntrypointWriterAuthority] = None
_SINGLETON_LOCK = threading.Lock()
_MODULE_ALIASES = ("bot.entrypoint_writer_authority", "entrypoint_writer_authority")
_CANONICAL_MODULE_ATTR = "_NIJA_CANONICAL_ENTRYPOINT_WRITER_MODULE"
_LEGACY_MODULE_ATTR = "_NIJA_ENTRYPOINT_WRITER_AUTHORITY_MODULE"
_CANONICAL_RUNTIME_ATTR = "_NIJA_CANONICAL_ENTRYPOINT_WRITER_RUNTIME"


def _runtime_preference(runtime: Any) -> tuple[int, int]:
    """Rank process-local runtime candidates without granting authority."""

    if runtime is None:
        return (0, 0)
    acquired = bool(getattr(runtime, "acquired", False))
    lost = bool(getattr(runtime, "lost", True))
    local = bool(getattr(runtime, "_local_fallback", False))
    generation = 0
    try:
        generation = int(getattr(runtime, "_generation", 0) or 0)
    except (TypeError, ValueError):
        pass
    if acquired and not lost and not local:
        return (4, generation)
    if acquired and not lost:
        return (3, generation)
    if not lost:
        return (2, generation)
    return (1, generation)


def bind_entrypoint_writer_authority_aliases(
    runtime: Optional[EntrypointWriterAuthority] = None,
) -> Optional[EntrypointWriterAuthority]:
    """Converge both supported import names onto one module and singleton.

    Production still contains compatibility imports for both the package and
    top-level module names.  Importing this file twice under those names used
    to create two independent ``_SINGLETON`` objects.  Later exact-owner guards
    could therefore inspect an unacquired duplicate while the real runtime was
    renewing the Redis lease.

    This function only converges process-local object identity.  It never
    acquires, renews, releases, or reconstructs Redis authority.  When called
    with an explicit runtime (the canonical post-acquisition path), that exact
    object wins.  Otherwise the best already-existing candidate is retained.
    """

    global _SINGLETON

    current_module = sys.modules.get(__name__)
    if not isinstance(current_module, ModuleType):
        return runtime

    modules: list[ModuleType] = [current_module]
    for name in _MODULE_ALIASES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and module not in modules:
            modules.append(module)
    for module_attr in (_CANONICAL_MODULE_ATTR, _LEGACY_MODULE_ATTR):
        prior_module = getattr(builtins, module_attr, None)
        if isinstance(prior_module, ModuleType) and prior_module not in modules:
            modules.append(prior_module)

    selected: Any = runtime
    if selected is None:
        candidates = [getattr(module, "_SINGLETON", None) for module in modules]
        candidates.extend(
            (
                getattr(builtins, _CANONICAL_RUNTIME_ATTR, None),
                getattr(builtins, "_NIJA_PREBOT_WRITER_AUTHORITY_RUNTIME", None),
            )
        )
        selected = max(candidates, key=_runtime_preference, default=None)

    _SINGLETON = selected
    for module in modules:
        try:
            module._SINGLETON = selected
        except Exception:
            pass
    for name in _MODULE_ALIASES:
        sys.modules[name] = current_module
    setattr(builtins, _CANONICAL_MODULE_ATTR, current_module)
    setattr(builtins, _LEGACY_MODULE_ATTR, current_module)
    if selected is not None:
        setattr(builtins, _CANONICAL_RUNTIME_ATTR, selected)
    os.environ["NIJA_ENTRYPOINT_WRITER_MODULE_IDENTITY_CONVERGED"] = "1"
    return selected


def get_entrypoint_writer_authority() -> EntrypointWriterAuthority:
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is None:
            _SINGLETON = EntrypointWriterAuthority()
        runtime = _SINGLETON
    bind_entrypoint_writer_authority_aliases(runtime)
    return runtime


# Bind the module names before any caller can create a compatibility-path
# singleton.  The explicit post-acquisition bind in bot_main then pins the
# exact acquired runtime for the rest of the process.
bind_entrypoint_writer_authority_aliases()
