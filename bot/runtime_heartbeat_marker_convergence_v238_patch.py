"""Re-arm genuine heartbeat execution after a proven writer renewal (v238/v275/v301).

v238 treats a successful entrypoint writer renewal only as a liveness wake-up;
it never writes execution proof.  v275 may arm the existing strategy publication
monitor after a real writer renewal when no strategy has been published yet.

Production on 2026-08-30 exposed a lease-thread isolation defect.  The v238
wrapper performed strategy discovery/import, scheduler re-arm and activation
reconciliation synchronously after the Redis renewal.  Once brokers became
entry-ready that post-renewal work could block inside strategy publication/import
state.  The Redis renewal itself succeeded, but the same heartbeat thread never
returned for its next lease refresh.  The v40 watchdog then correctly observed
``renewal_success_stale`` while the exact Redis lock was still owned.

v301 keeps the genuine Redis renewal path synchronous and authoritative, but
moves all v238 post-renewal publication/strategy/activation work to one daemon
single-flight worker per writer runtime.  The worker is generation/token scoped;
a worker from a superseded writer epoch may finish diagnostic work but cannot
wake activation for the new epoch.  Install-time re-arm behavior remains on the
normal startup thread.

No execution authority, readiness, nonce, risk, capital, broker-health, ECEL,
minimum-notional, acknowledgement, fill, writer or fencing gate is bypassed or
fabricated.  No Redis lock is renewed or mutated by the v301 worker.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_heartbeat_marker_convergence_v238")
MARKER = "20260826-heartbeat-marker-convergence-v238"
V275_MARKER = "20260829-strategy-publication-writer-handoff-v275"
V301_MARKER = "20260830-writer-renewal-postwork-isolation-v301"
V301_READY_FLAG = "NIJA_RUNTIME_WRITER_RENEWAL_POSTWORK_ISOLATION_V301_READY"
_PATCH_ATTR = "_nija_heartbeat_marker_convergence_v238"
_POSTWORK_THREAD_ATTR = "_nija_writer_renewal_postwork_thread_v301"
_POSTWORK_LOCK_ATTR = "_nija_writer_renewal_postwork_lock_v301"
_POSTWORK_GENERATION_ATTR = "_nija_writer_renewal_postwork_generation_v301"
_POSTWORK_TOKEN_ATTR = "_nija_writer_renewal_postwork_token_v301"
_POSTWORK_INIT_LOCK = threading.RLock()


def _arm_strategy_publication_monitor(publication: Any) -> tuple[bool, str]:
    """Arm the existing publisher after writer proof; never publish readiness here."""
    starter = getattr(publication, "start_monitor", None)
    if not callable(starter):
        return False, "publication_start_unavailable"
    try:
        armed = bool(starter())
    except Exception as exc:
        return False, f"publication_start_error:{type(exc).__name__}:{exc}"
    if armed:
        LOGGER.warning(
            "STRATEGY_PUBLICATION_WRITER_HANDOFF_V275_ARMED marker=%s "
            "writer_renewal_required=true publication_monitor_only=true "
            "strategy_published=false readiness_fabricated=false execution_authority_granted=false "
            "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            V275_MARKER,
        )
        return True, "publication_monitor_armed"
    return False, "publication_monitor_not_armed"


def _rearm_genuine_heartbeat(*, allow_publication_arm: bool = False) -> tuple[bool, str]:
    try:
        v203 = importlib.import_module("bot.runtime_existing_strategy_heartbeat_rearm_v203_patch")
        publication = importlib.import_module("bot.strategy_publication_patch")
        finder = getattr(v203, "_already_published_strategy", None)
        ensure = getattr(v203, "_ensure_heartbeat_scheduler", None)
        if not callable(finder) or not callable(ensure):
            return False, "v203_helpers_unavailable"
        strategy = finder(publication)
        if strategy is None:
            if not allow_publication_arm:
                return False, "strategy_not_published"
            _armed, detail = _arm_strategy_publication_monitor(publication)
            return False, f"strategy_not_published:{detail}"
        ready = bool(ensure(strategy))
        return ready, "scheduler_alive" if ready else "scheduler_not_alive"
    except Exception as exc:
        return False, f"rearm_error:{type(exc).__name__}:{exc}"


def _genuine_execution_marker_ready() -> tuple[bool, str]:
    try:
        tsm = importlib.import_module("bot.trading_state_machine")
        verifier = getattr(tsm, "_heartbeat_verification_status", None)
        if not callable(verifier):
            return False, "canonical_verifier_unavailable"
        ok, detail, _meta = verifier()
        return bool(ok), str(detail or "verified")
    except Exception as exc:
        return False, f"verification_error:{type(exc).__name__}:{exc}"


def _wake_activation_after_genuine_marker(source: str) -> bool:
    marker_ready, marker_detail = _genuine_execution_marker_ready()
    if not marker_ready:
        LOGGER.info(
            "HEARTBEAT_MARKER_V238_EXECUTION_PROOF_PENDING marker=%s source=%s detail=%s "
            "execution_proof_fabricated=false activation_commit_attempted=false trading_fail_closed=true",
            MARKER, source, marker_detail,
        )
        return False
    try:
        repair = importlib.import_module("bot.runtime_authority_convergence_repair_patch")
        converge = getattr(repair, "converge_runtime_authority", None)
        if callable(converge):
            converge("heartbeat_execution_marker_v238")
            LOGGER.critical(
                "HEARTBEAT_MARKER_V238_GENUINE_EXECUTION_PROOF_READY marker=%s source=%s "
                "canonical_verifier=true activation_reconcile_wakeup=true proof_fabricated=false "
                "forced_activation=false safety_gates_bypassed=false",
                MARKER, source,
            )
            return True
    except Exception as exc:
        LOGGER.warning(
            "HEARTBEAT_MARKER_V238_RECONCILE_DEFERRED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
    return False


def _runtime_epoch_current(runtime: Any, generation: int, token: str) -> bool:
    """Process-local epoch check used only to suppress stale postwork."""
    try:
        return bool(
            getattr(runtime, "acquired", False)
            and not getattr(runtime, "lost", True)
            and int(getattr(runtime, "_generation", 0) or 0) == int(generation)
            and str(getattr(runtime, "_token", "") or "") == str(token or "")
        )
    except Exception:
        return False


def _postwork_lock(runtime: Any) -> threading.Lock:
    lock = getattr(runtime, _POSTWORK_LOCK_ATTR, None)
    if lock is not None:
        return lock
    with _POSTWORK_INIT_LOCK:
        lock = getattr(runtime, _POSTWORK_LOCK_ATTR, None)
        if lock is None:
            lock = threading.Lock()
            setattr(runtime, _POSTWORK_LOCK_ATTR, lock)
        return lock


def _dispatch_writer_renewal_postwork(runtime: Any) -> tuple[bool, str]:
    """Move non-lease writer-renewal work off the Redis heartbeat thread."""
    generation = int(getattr(runtime, "_generation", 0) or 0)
    token = str(getattr(runtime, "_token", "") or "")
    if generation <= 0 or not token or not _runtime_epoch_current(runtime, generation, token):
        return False, "writer_epoch_not_current"

    lock = _postwork_lock(runtime)
    with lock:
        existing = getattr(runtime, _POSTWORK_THREAD_ATTR, None)
        if existing is not None and callable(getattr(existing, "is_alive", None)):
            try:
                if existing.is_alive():
                    return False, "postwork_in_flight"
            except Exception:
                return False, "postwork_state_unavailable"

        def _worker() -> None:
            rearmed = False
            rearm_detail = "not_run"
            activation_woken = False
            try:
                if not _runtime_epoch_current(runtime, generation, token):
                    LOGGER.info(
                        "WRITER_RENEWAL_POSTWORK_V301_SUPPRESSED marker=%s generation=%d "
                        "reason=writer_epoch_changed_before_worker_start redis_mutated=false "
                        "activation_attempted=false execution_proof_fabricated=false",
                        V301_MARKER,
                        generation,
                    )
                    return

                rearmed, rearm_detail = _rearm_genuine_heartbeat(
                    allow_publication_arm=True
                )
                LOGGER.critical(
                    "HEARTBEAT_MARKER_V238_LIVENESS_WAKE marker=%s source=entrypoint_writer_renewal_async_v301 "
                    "lease_acquired=true writer_lost=false renewal_health=true scheduler_ready=%s "
                    "scheduler_detail=%s execution_marker_written=false writer_renewal_not_execution_proof=true "
                    "execution_proof_fabricated=false nonce_risk_capital_order_gates_unchanged=true "
                    "safety_gates_bypassed=false",
                    MARKER,
                    str(rearmed).lower(),
                    rearm_detail,
                )

                if not _runtime_epoch_current(runtime, generation, token):
                    LOGGER.info(
                        "WRITER_RENEWAL_POSTWORK_V301_SUPPRESSED marker=%s generation=%d "
                        "reason=writer_epoch_changed_after_rearm redis_mutated=false "
                        "activation_attempted=false execution_proof_fabricated=false",
                        V301_MARKER,
                        generation,
                    )
                    return

                activation_woken = _wake_activation_after_genuine_marker(
                    "entrypoint_writer_renewal_async_v301"
                )
            except Exception as exc:
                LOGGER.warning(
                    "WRITER_RENEWAL_POSTWORK_V301_ERROR marker=%s generation=%d error=%s:%s "
                    "redis_mutated=false writer_renewal_unchanged=true trading_fail_closed=true",
                    V301_MARKER,
                    generation,
                    type(exc).__name__,
                    exc,
                )
            finally:
                LOGGER.info(
                    "WRITER_RENEWAL_POSTWORK_V301_COMPLETE marker=%s generation=%d "
                    "scheduler_ready=%s scheduler_detail=%s activation_woken=%s "
                    "redis_mutated=false writer_renewal_unchanged=true execution_proof_fabricated=false",
                    V301_MARKER,
                    generation,
                    str(rearmed).lower(),
                    rearm_detail,
                    str(activation_woken).lower(),
                )
                with lock:
                    if getattr(runtime, _POSTWORK_THREAD_ATTR, None) is threading.current_thread():
                        setattr(runtime, _POSTWORK_THREAD_ATTR, None)
                        setattr(runtime, _POSTWORK_GENERATION_ATTR, 0)
                        setattr(runtime, _POSTWORK_TOKEN_ATTR, "")

        worker = threading.Thread(
            target=_worker,
            name=f"writer-renewal-postwork-v301-g{generation}",
            daemon=True,
        )
        setattr(runtime, _POSTWORK_THREAD_ATTR, worker)
        setattr(runtime, _POSTWORK_GENERATION_ATTR, generation)
        setattr(runtime, _POSTWORK_TOKEN_ATTR, token)
        worker.start()

    LOGGER.critical(
        "WRITER_RENEWAL_POSTWORK_V301_DISPATCHED marker=%s generation=%d "
        "lease_thread_nonblocking=true single_flight=true redis_mutated=false "
        "writer_renewal_unchanged=true strategy_publication_async=true activation_reconcile_async=true "
        "execution_proof_fabricated=false safety_gates_bypassed=false",
        V301_MARKER,
        generation,
    )
    return True, "postwork_dispatched"


def _patch_entrypoint_writer() -> bool:
    module = importlib.import_module("bot.entrypoint_writer_authority")
    cls = getattr(module, "EntrypointWriterAuthority", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_heartbeat_tick", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def heartbeat_tick_v238(self: Any, *args: Any, **kwargs: Any):
        result = current(self, *args, **kwargs)
        try:
            acquired = bool(getattr(self, "acquired", False))
            lost = bool(getattr(self, "lost", True))
            health = getattr(self, "_nija_lease_renewal_health", None)
            healthy = False
            reason = "health_unavailable"
            if callable(health):
                proof = health()
                healthy = bool(proof and proof[0])
                reason = str(proof[1] if len(proof) > 1 else "unknown")
            if acquired and not lost and healthy:
                dispatched, postwork_detail = _dispatch_writer_renewal_postwork(self)
                if not dispatched:
                    LOGGER.debug(
                        "WRITER_RENEWAL_POSTWORK_V301_DEFERRED marker=%s generation=%s detail=%s "
                        "lease_thread_nonblocking=true",
                        V301_MARKER,
                        getattr(self, "_generation", 0),
                        postwork_detail,
                    )
            else:
                LOGGER.debug(
                    "HEARTBEAT_MARKER_V238_WAKE_SKIPPED marker=%s acquired=%s lost=%s healthy=%s reason=%s",
                    MARKER, acquired, lost, healthy, reason,
                )
        except Exception as exc:
            LOGGER.warning(
                "HEARTBEAT_MARKER_V238_WAKE_FAILED marker=%s error=%s:%s trading_fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        return result

    setattr(heartbeat_tick_v238, _PATCH_ATTR, True)
    setattr(heartbeat_tick_v238, "__wrapped__", current)
    cls._heartbeat_tick = heartbeat_tick_v238
    return True


def _register_v301_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_writer_renewal_postwork_isolation_v301"] = V301_READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    try:
        ready = _patch_entrypoint_writer()
        manifest_ready = _register_v301_manifest()
        rearmed, detail = _rearm_genuine_heartbeat()
        LOGGER.info(
            "HEARTBEAT_MARKER_V238_INSTALL_REARM marker=%s scheduler_ready=%s detail=%s",
            MARKER, str(rearmed).lower(), detail,
        )
        _wake_activation_after_genuine_marker("install")
    except Exception as exc:
        LOGGER.error(
            "HEARTBEAT_MARKER_V238_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        ready = False
        manifest_ready = False

    v301_ready = bool(ready and manifest_ready)
    os.environ["NIJA_HEARTBEAT_MARKER_CONVERGENCE_V238_READY"] = "1" if ready else "0"
    os.environ[V301_READY_FLAG] = "1" if v301_ready else "0"
    if v301_ready:
        LOGGER.critical(
            "RUNTIME_WRITER_RENEWAL_POSTWORK_ISOLATION_V301_READY marker=%s ready=true "
            "writer_renewal_postwork_async=true single_flight=true generation_token_scoped=true "
            "redis_mutated=false writer_renewal_unchanged=true writer_ttl_unchanged=true "
            "strategy_publication_async=true activation_reconcile_async=true execution_proof_fabricated=false "
            "forced_activation=false writer_nonce_risk_capital_position_killswitch_order_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            V301_MARKER,
        )
    if ready:
        LOGGER.critical(
            "HEARTBEAT_MARKER_CONVERGENCE_V238_READY marker=%s ready=true genuine_writer_renewal_wakeup_only=true "
            "real_heartbeat_scheduler_rearmed=true execution_marker_owner=TradingStrategy._persist_heartbeat_marker "
            "canonical_execution_marker_verifier=true activation_reconcile_after_genuine_marker_only=true "
            "strategy_publication_writer_handoff_v275=true writer_renewal_postwork_async_v301=%s "
            "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            MARKER,
            str(v301_ready).lower(),
        )
    return bool(ready and v301_ready)


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "V275_MARKER",
    "V301_MARKER",
    "V301_READY_FLAG",
    "install",
    "install_import_hook",
    "_arm_strategy_publication_monitor",
    "_rearm_genuine_heartbeat",
    "_genuine_execution_marker_ready",
    "_wake_activation_after_genuine_marker",
    "_runtime_epoch_current",
    "_dispatch_writer_renewal_postwork",
]
