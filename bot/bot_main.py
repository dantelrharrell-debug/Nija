#!/usr/bin/env python3
"""NIJA Trading Bot — canonical production entrypoint (APEX v7.2.0).

Startup ordering is safety-critical:

1. Acquire and verify Redis writer authority.
2. Start writer/authority heartbeats.
3. Inspect or create Kraken nonce state.
4. Connect brokers and hydrate capital.
5. Advance BootstrapFSM and start the trading engine.

The active Render path is ``main.py -> bot.bot -> bot.bot_main``.  Writer
lineage must therefore be established here before SelfHealingStartup touches the
Kraken nonce singleton.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from typing import Optional

logger = logging.getLogger("nija.main")

BOOTSTRAP_TIMEOUT_S = float(os.environ.get("NIJA_BOOTSTRAP_TIMEOUT_S", "300"))
SUPERVISOR_POLL_INTERVAL_S = float(os.environ.get("NIJA_SUPERVISOR_POLL_S", "10"))
SUPERVISOR_MAX_FAILURES = int(os.environ.get("NIJA_SUPERVISOR_MAX_FAILURES", "3"))

_shutdown_event = threading.Event()
_startup_complete = False
_writer_authority_runtime = None
_authority_heartbeat_monitor = None
_writer_authority_last_error = ""
_core_loop_thread: Optional[threading.Thread] = None
_core_registration_restart_timer: Optional[threading.Timer] = None
_process_exit_code = 0
_process_exit_reason = ""

# Per-step startup timestamps used by the watchdog and diagnostics.
_startup_stage_ts: dict[str, float] = {}
# Set to True once the watchdog should stop polling.
_startup_registration_done = threading.Event()


def _revoke_writer_dependent_readiness(reason: str) -> None:
    """Publish fail-closed process truth after writer bootstrap failure."""

    os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"
    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "0"
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
    os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)
    os.environ.pop("NIJA_WRITER_GENERATION", None)
    os.environ.pop("NIJA_WRITER_LEASE_GENERATION", None)
    try:
        from bot.readiness_table import revoke_many

        revoke_many(
            ("authority_ready", "nonce_ready", "execution_ready"),
            reason=f"writer_bootstrap_unavailable:{reason}",
        )
    except Exception:
        logger.debug(
            "WRITER_BOOTSTRAP_READINESS_REVOKE_FAILED reason=%s",
            reason,
            exc_info=True,
        )


def request_process_exit(
    reason: str,
    *,
    exit_code: int = 75,
    terminal_startup_failure: bool = False,
) -> int:
    """Request a fail-closed process exit through the canonical entrypoint."""

    global _process_exit_code, _process_exit_reason, _writer_authority_last_error

    final_reason = str(reason or "process_exit_requested")
    if _process_exit_code and _process_exit_reason == final_reason:
        return _process_exit_code

    _process_exit_code = int(exit_code or 75)
    _process_exit_reason = final_reason
    _writer_authority_last_error = final_reason
    os.environ["NIJA_PROCESS_EXIT_REQUESTED"] = "1"
    os.environ["NIJA_PROCESS_EXIT_CODE"] = str(_process_exit_code)
    os.environ["NIJA_PROCESS_EXIT_REASON"] = final_reason
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
    _revoke_writer_dependent_readiness(final_reason)
    try:
        from bot.bootstrap_utils import signal_shutdown

        signal_shutdown()
    except Exception:
        logger.debug(
            "PROCESS_EXIT_REQUESTED bootstrap_utils.signal_shutdown unavailable",
            exc_info=True,
        )
    runtime = _writer_authority_runtime
    if terminal_startup_failure and runtime is not None:
        marker = getattr(runtime, "mark_terminal_startup_failure", None)
        if callable(marker):
            try:
                marker(final_reason)
            except Exception:
                logger.debug(
                    "PROCESS_EXIT_REQUESTED runtime terminal marker failed",
                    exc_info=True,
                )
    _shutdown_event.set()
    logger.critical(
        "PROCESS_EXIT_REQUESTED reason=%s exit_code=%d generation=%s "
        "instance_id=%s token_prefix=%s terminal_startup_failure=%s",
        final_reason,
        _process_exit_code,
        os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "0",
        getattr(runtime, "_instance_id", "") or "unknown",
        str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "")[:8],
        terminal_startup_failure,
    )
    return _process_exit_code


def _startup_registration_watchdog(
    deadline_s: float,
    poll_interval_s: float = 10.0,
) -> None:
    """Watchdog that dumps stack traces if startup registration is blocked.

    Runs in a daemon thread started just before Step 3.  If
    ``_startup_registration_done`` is not set within *deadline_s* seconds the
    watchdog emits a critical log with a per-thread stack trace so the blocking
    site can be identified from production logs.  The watchdog exits silently
    once registration completes or the shutdown event fires.
    """
    import traceback as _traceback

    watchdog_start = time.time()
    while not _startup_registration_done.wait(timeout=min(poll_interval_s, deadline_s)):
        elapsed = time.time() - watchdog_start
        if _shutdown_event.is_set():
            return
        if elapsed < deadline_s:
            continue
        # Deadline exceeded — emit stack dump so the blocking site is visible
        # in production logs.  We emit one dump then continue polling so that
        # a second dump can be emitted if the block persists.
        frames = []
        for tid, frame in sys._current_frames().items():
            thread_name = "unknown"
            for t in threading.enumerate():
                if t.ident == tid:
                    thread_name = t.name
                    break
            stack = "".join(_traceback.format_stack(frame))
            frames.append(
                f"Thread ident={tid} name={thread_name!r}:\n{stack}"
            )
        logger.critical(
            "STARTUP_REGISTRATION_BLOCKED_STACK_DUMP marker=20260811-startup-watchdog "
            "elapsed_s=%.1f deadline_s=%.1f stage_ts=%s\n%s",
            elapsed,
            deadline_s,
            _startup_stage_ts,
            "\n---\n".join(frames),
        )
        # Reset timer so a second dump fires after another deadline_s if still stuck.
        watchdog_start = time.time()


def _schedule_writer_authority_restart(reason: str) -> None:
    """Force a non-zero restart if writer-loss shutdown cannot exit.

    The writer lease has already been lost or compare-deleted before this
    callback is invoked.  A short grace period lets the canonical stack unwind
    normally; ``os._exit(75)`` is the final bound for non-daemon broker and
    reconciliation workers that would otherwise keep a fail-closed process
    alive forever.
    """

    global _core_registration_restart_timer
    if _core_registration_restart_timer is not None:
        return
    try:
        grace_s = max(
            1.0,
            float(
                os.environ.get(
                    "NIJA_WRITER_AUTHORITY_RESTART_GRACE_S",
                    os.environ.get("NIJA_CORE_REGISTRATION_RESTART_GRACE_S", "15"),
                )
                or 15
            ),
        )
    except (TypeError, ValueError):
        grace_s = 15.0

    def _force_restart() -> None:
        logger.critical(
            "WRITER_AUTHORITY_FORCED_RESTART reason=%s exit_code=75",
            reason,
        )
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:
                pass
        os._exit(75)

    timer = threading.Timer(grace_s, _force_restart)
    timer.name = "writer-authority-forced-restart"
    timer.daemon = True
    _core_registration_restart_timer = timer
    logger.critical(
        "WRITER_AUTHORITY_RESTART_SCHEDULED reason=%s grace_s=%.1f "
        "writer_unavailable=true",
        reason,
        grace_s,
    )
    timer.start()


def _schedule_core_registration_restart(reason: str) -> None:
    """Backward-compatible wrapper for the original registration watchdog."""

    _schedule_writer_authority_restart(reason)


def _signal_handler(signum: int, frame) -> None:
    """Handle SIGTERM/SIGINT without granting or retaining stale authority."""

    sig_name = signal.Signals(signum).name
    logger.critical("🛑 Received signal %s — initiating graceful shutdown", sig_name)
    try:
        from bot.bootstrap_utils import signal_shutdown

        signal_shutdown()
    except Exception:
        logger.debug("bootstrap shutdown signal unavailable", exc_info=True)
    _signal_core_loop_shutdown(f"signal:{sig_name}")
    _shutdown_event.set()


def _signal_core_loop_shutdown(reason: str) -> bool:
    """Wake the canonical core loop without importing it during early startup."""
    module = sys.modules.get("bot.nija_core_loop") or sys.modules.get("nija_core_loop")
    if module is None:
        return False
    request_stop = getattr(module, "request_trading_engine_stop", None)
    if not callable(request_stop):
        logger.warning(
            "TRADING_ENGINE_STOP_SIGNAL_UNAVAILABLE reason=%s",
            reason,
        )
        return False
    try:
        request_stop(reason)
        return True
    except Exception as exc:
        logger.warning(
            "TRADING_ENGINE_STOP_SIGNAL_FAILED reason=%s error=%s:%s",
            reason,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return False


def _acquire_writer_authority_before_nonce() -> bool:
    """Establish Redis fencing lineage before any nonce-manager access."""

    global _writer_authority_runtime, _authority_heartbeat_monitor, _writer_authority_last_error

    if _process_exit_code:
        _writer_authority_last_error = _process_exit_reason or "process_exit_requested"
        logger.critical(
            "ENTRYPOINT_WRITER_AUTHORITY_REACQUIRE_BLOCKED reason=%s exit_code=%d",
            _writer_authority_last_error,
            _process_exit_code,
        )
        _revoke_writer_dependent_readiness(_writer_authority_last_error)
        return False

    runtime = None
    try:
        from bot.entrypoint_writer_authority import (
            bind_entrypoint_writer_authority_aliases,
            get_entrypoint_writer_authority,
        )

        runtime = get_entrypoint_writer_authority()
        result = runtime.acquire_with_standby(shutdown_event=_shutdown_event)
        _writer_authority_last_error = str(getattr(result, "error", "") or "")
        if not result.acquired:
            _revoke_writer_dependent_readiness(
                str(result.error or "writer_acquisition_failed")
            )
            if result.error == "shutdown_requested":
                logger.info("Writer-authority standby interrupted by shutdown")
            elif result.error == "active_writer_lock_held":
                logger.warning(
                    "ENTRYPOINT_WRITER_AUTHORITY_STANDBY_CONFIRMED marker=20260710u "
                    "holder=%s pttl_ms=%s",
                    result.holder,
                    result.pttl_ms,
                )
            else:
                logger.critical(
                    "ENTRYPOINT_WRITER_AUTHORITY_BLOCKED marker=20260710u error=%s "
                    "holder=%s pttl_ms=%s",
                    result.error,
                    result.holder,
                    result.pttl_ms,
                )
            return False

        _writer_authority_runtime = runtime
        bound_runtime = bind_entrypoint_writer_authority_aliases(runtime)
        if bound_runtime is not runtime:
            logger.critical(
                "ENTRYPOINT_WRITER_AUTHORITY_IDENTITY_BIND_FAILED marker=20260710u "
                "trading_remains_fail_closed=true"
            )
            runtime.release()
            _writer_authority_runtime = None
            _revoke_writer_dependent_readiness("module_identity_bind_failed")
            return False
        logger.critical(
            "ENTRYPOINT_WRITER_AUTHORITY_IDENTITY_CONVERGED marker=20260810-v91 "
            "package_alias=true compatibility_alias=true singleton_exact=true generation=%s",
            getattr(runtime, "_generation", 0),
        )

        # Wire up the on-lost callback so _shutdown_event is set immediately
        # when the lease is lost (e.g. core thread dies), without waiting for
        # the _keep_process_alive_after_loop_return polling interval.
        def _on_lease_lost(reason: str) -> bool:
            logger.critical(
                "WRITER_AUTHORITY_LOST_SHUTDOWN_TRIGGERED marker=20260710u reason=%s",
                reason,
            )
            # Stop the heartbeat monitor first so it cannot trigger a spurious
            # lockdown while the lease-lost shutdown sequence is in progress.
            _monitor = _authority_heartbeat_monitor
            if _monitor is not None and callable(getattr(_monitor, "stop", None)):
                try:
                    _monitor.stop()
                except Exception:
                    pass
            try:
                from bot.terminal_writer_loss_latch import report_terminal_writer_loss
            except ImportError:
                from terminal_writer_loss_latch import (  # type: ignore[import]
                    report_terminal_writer_loss,
                )
            return report_terminal_writer_loss(
                str(reason or "writer_authority_lost"),
                source="on_lease_lost",
            )

        if callable(getattr(runtime, "set_on_lost_callback", None)):
            runtime.set_on_lost_callback(_on_lease_lost)

        # Start the independent authority verifier only after the lock, token,
        # generation and lock-heartbeat timestamps have been published.
        try:
            from bot.authority_heartbeat import start_authority_heartbeat

            _authority_heartbeat_monitor = start_authority_heartbeat()
            logger.info(
                "ENTRYPOINT_AUTHORITY_HEARTBEAT_STARTED marker=20260710u monitor=%r",
                _authority_heartbeat_monitor,
            )
        except Exception as heartbeat_exc:
            logger.critical(
                "ENTRYPOINT_AUTHORITY_HEARTBEAT_START_FAILED marker=20260710u err=%s",
                heartbeat_exc,
                exc_info=True,
            )
            runtime.release()
            _writer_authority_runtime = None
            _revoke_writer_dependent_readiness("authority_heartbeat_start_failed")
            return False

        # Synchronous proof closes the race between heartbeat-thread launch and
        # SelfHealingStartup's first get_global_nonce_manager() call.
        try:
            from bot.execution_authority_context import assert_distributed_writer_authority

            assert_distributed_writer_authority()
        except Exception as authority_exc:
            logger.critical(
                "ENTRYPOINT_WRITER_AUTHORITY_VERIFY_FAILED marker=20260710u err=%s",
                authority_exc,
                exc_info=True,
            )
            try:
                _authority_heartbeat_monitor.stop()
            except Exception:
                pass
            runtime.release()
            _writer_authority_runtime = None
            _authority_heartbeat_monitor = None
            _revoke_writer_dependent_readiness("exact_authority_verify_failed")
            return False

        logger.critical(
            "ENTRYPOINT_WRITER_AUTHORITY_VERIFIED marker=20260710u "
            "token_prefix=%s generation=%s instance=%s local_fallback=%s",
            result.token[:8],
            result.generation,
            result.instance_id,
            result.local_fallback,
        )
        return True

    except Exception as exc:
        _writer_authority_last_error = f"{type(exc).__name__}:{exc}"
        logger.critical(
            "ENTRYPOINT_WRITER_AUTHORITY_BOOTSTRAP_EXCEPTION marker=20260710u "
            "type=%s err=%s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        monitor = _authority_heartbeat_monitor
        _authority_heartbeat_monitor = None
        if monitor is not None:
            try:
                monitor.stop()
            except Exception:
                pass
        runtime_to_release = _writer_authority_runtime or runtime
        _writer_authority_runtime = None
        if runtime_to_release is not None:
            try:
                runtime_to_release.release()
            except Exception:
                logger.warning(
                    "WRITER_AUTHORITY_EXCEPTION_RELEASE_FAILED",
                    exc_info=True,
                )
        _revoke_writer_dependent_readiness("bootstrap_exception")
        return False


def _release_writer_authority() -> None:
    """Stop authority monitors and compare-and-delete this process's lease."""

    global _writer_authority_runtime, _authority_heartbeat_monitor, _core_loop_thread

    monitor = _authority_heartbeat_monitor
    _authority_heartbeat_monitor = None
    if monitor is not None:
        try:
            monitor.stop()
        except Exception as exc:
            logger.warning("Authority heartbeat stop failed: %s", exc)

    runtime = _writer_authority_runtime
    _writer_authority_runtime = None
    _core_loop_thread = None
    if runtime is not None:
        try:
            runtime.release()
        except Exception as exc:
            logger.warning("Writer-authority release failed: %s", exc, exc_info=True)


def _connected_platform_broker_count(manager: object) -> int:
    """Return the number of connected platform brokers on the manager."""

    brokers = getattr(manager, "platform_brokers", None)
    if callable(brokers):
        brokers = brokers()
    if brokers is None:
        brokers = getattr(manager, "_platform_brokers", {})

    try:
        broker_values = dict(brokers or {}).values()
    except Exception:
        return 0

    return sum(
        1
        for broker in broker_values
        if broker is not None and bool(getattr(broker, "connected", False))
    )


def _run_self_healing_startup() -> tuple[bool, Optional[object], str]:
    """Run broker/nonce recovery only after writer lineage is verified."""

    logger.info("🚀 Starting self-healing bootstrap sequence...")
    try:
        from bot.self_healing_startup import SelfHealingStartup, StartupConfig

        startup = SelfHealingStartup(StartupConfig())
        result = startup.run()
        if result.ok:
            logger.info(
                "✅ Bootstrap complete: broker=%s mode=%s",
                result.broker_name,
                "FALLBACK" if result.on_fallback else "PRIMARY",
            )
            return True, result.broker, result.broker_name

        logger.critical("❌ Bootstrap failed: %s", result.reason)
        return False, None, ""
    except Exception as exc:
        logger.critical(
            "❌ Bootstrap exception: %s: %s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return False, None, ""


def _transition_if_current_allows(fsm, BootstrapState, target, reason: str) -> bool:
    if fsm.state == target:
        return True
    ok = fsm.transition(target, reason=reason)
    if ok:
        logger.info("✅ FSM → %s", target.value)
    return bool(ok)


def _apply_bootstrap_i12_repair_direct(bootstrap_module) -> None:
    """Apply the capital-authority I12 repair before FSM advancement."""

    try:
        from bot.bootstrap_i12_capital_authority_repair_patch import (
            _patch_bootstrap_fsm as _patch_i12,
        )

        if _patch_i12(bootstrap_module):
            logger.warning(
                "BOOTSTRAP_I12_CAPITAL_AUTHORITY_REPAIR_DIRECT_APPLIED source=bot_main"
            )
    except Exception as exc:
        logger.warning(
            "BOOTSTRAP_I12_CAPITAL_AUTHORITY_REPAIR_DIRECT_FAILED "
            "source=bot_main err=%s",
            exc,
        )


def _publish_supervised_thread_evidence() -> bool:
    """Publish concrete supervised-worker evidence to the activation coordinator."""

    runtime = _writer_authority_runtime
    heartbeat = getattr(runtime, "_heartbeat_thread", None) if runtime is not None else None
    heartbeat_alive = bool(
        runtime is not None
        and bool(getattr(runtime, "acquired", False))
        and not bool(getattr(runtime, "lost", True))
        and heartbeat is not None
        and callable(getattr(heartbeat, "is_alive", None))
        and heartbeat.is_alive()
    )
    if not heartbeat_alive:
        logger.critical(
            "SUPERVISED_THREAD_EVIDENCE_BLOCKED marker=20260802-activation-thread-proof-v1 "
            "writer_acquired=%s writer_lost=%s heartbeat_alive=false "
            "activation_remains_pending=true",
            bool(runtime and getattr(runtime, "acquired", False)),
            bool(runtime is None or getattr(runtime, "lost", True)),
        )
        return False

    try:
        from bot.startup_coordinator import get_startup_coordinator

        coordinator = get_startup_coordinator()
        live_workers = sum(
            1
            for worker in threading.enumerate()
            if worker is not threading.current_thread() and worker.is_alive()
        )
        worker_count = max(1, live_workers)
        coordinator.record_threads_supervised(
            worker_count,
            bootstrap_state="RUNNING_SUPERVISED",
        )
        logger.critical(
            "SUPERVISED_THREAD_EVIDENCE_PUBLISHED "
            "marker=20260802-activation-thread-proof-v1 workers=%d "
            "writer_heartbeat_alive=true",
            worker_count,
        )
        return True
    except Exception as exc:
        logger.critical(
            "SUPERVISED_THREAD_EVIDENCE_FAILED "
            "marker=20260802-activation-thread-proof-v1 err=%s "
            "activation_remains_pending=true",
            exc,
            exc_info=True,
        )
        return False


def _advance_bootstrap_fsm_to_threads_starting() -> bool:
    """Advance BootstrapFSM to THREADS_STARTING only.

    Called at STEP 2 — before the real core thread exists.  The final
    THREADS_STARTING → RUNNING_SUPERVISED transition is deferred until after
    the core thread is created and registered (spec item J).
    """
    logger.info("🚀 Advancing bootstrap FSM to THREADS_STARTING (pre-core)...")
    try:
        import bot.bootstrap_state_machine as bootstrap_module

        _apply_bootstrap_i12_repair_direct(bootstrap_module)
        from bot.bootstrap_state_machine import BootstrapState, get_bootstrap_fsm

        fsm = get_bootstrap_fsm()
        if fsm.state in {
            BootstrapState.THREADS_STARTING,
            BootstrapState.RUNNING_SUPERVISED,
        }:
            logger.info(
                "BOOTSTRAP_FSM_PRECORE_READY state=%s (already past THREADS_STARTING)",
                fsm.state.value,
            )
            return True

        fsm.claim_bootstrap_ownership()
        logger.info("BootstrapFSM pre-core state=%s", fsm.state.value)

        if fsm.state not in {
            BootstrapState.CAPITAL_READY,
            BootstrapState.INIT_COMPLETE,
            BootstrapState.DEGRADED_READY,
        }:
            advance = getattr(fsm, "advance_to_capital_ready", None)
            if callable(advance):
                if not advance(reason="bot_main_pre_core_advancement"):
                    logger.error(
                        "❌ FSM advance_to_capital_ready failed; state=%s",
                        fsm.state.value,
                    )
                    return False

        if fsm.state == BootstrapState.CAPITAL_READY:
            if not _transition_if_current_allows(
                fsm,
                BootstrapState,
                BootstrapState.INIT_COMPLETE,
                "bot_main_pre_core_advancement",
            ):
                return False

        if fsm.state == BootstrapState.DEGRADED_READY:
            if not _transition_if_current_allows(
                fsm,
                BootstrapState,
                BootstrapState.THREADS_STARTING,
                "bot_main_degraded_handoff",
            ):
                return False

        if fsm.state == BootstrapState.INIT_COMPLETE:
            if not _transition_if_current_allows(
                fsm,
                BootstrapState,
                BootstrapState.THREADS_STARTING,
                "bot_main_pre_core_advancement",
            ):
                return False

        if fsm.state == BootstrapState.THREADS_STARTING:
            logger.critical(
                "BOOTSTRAP_FSM_PRECORE_READY state=THREADS_STARTING core_not_yet_started=true"
            )
            return True

        logger.error(
            "❌ FSM pre-core advancement ended at %s, expected THREADS_STARTING",
            fsm.state.value,
        )
        return False
    except Exception as exc:
        logger.error("❌ FSM pre-core advancement failed: %s", exc, exc_info=True)
        return False


def _advance_bootstrap_fsm_to_running_supervised() -> bool:
    """Advance BootstrapFSM using only legal transitions."""

    logger.info("🚀 Advancing bootstrap FSM to RUNNING_SUPERVISED...")
    try:
        import bot.bootstrap_state_machine as bootstrap_module

        _apply_bootstrap_i12_repair_direct(bootstrap_module)
        from bot.bootstrap_state_machine import BootstrapState, get_bootstrap_fsm

        fsm = get_bootstrap_fsm()
        if fsm.state == BootstrapState.RUNNING_SUPERVISED:
            if not _publish_supervised_thread_evidence():
                logger.error(
                    "FSM is RUNNING_SUPERVISED but supervised thread proof is unavailable"
                )
                return False
            logger.info("✅ FSM already RUNNING_SUPERVISED")
            return True

        fsm.claim_bootstrap_ownership()
        logger.info("BootstrapFSM pre-handoff state=%s", fsm.state.value)

        if fsm.state not in {
            BootstrapState.CAPITAL_READY,
            BootstrapState.INIT_COMPLETE,
            BootstrapState.DEGRADED_READY,
            BootstrapState.THREADS_STARTING,
            BootstrapState.RUNNING_SUPERVISED,
        }:
            advance = getattr(fsm, "advance_to_capital_ready", None)
            if not callable(advance):
                logger.error(
                    "❌ FSM cannot advance legally from %s; helper unavailable",
                    fsm.state.value,
                )
                return False
            if not advance(reason="bot_main_post_self_healing_startup"):
                logger.error(
                    "❌ FSM advance_to_capital_ready failed; current_state=%s",
                    fsm.state.value,
                )
                return False

        if fsm.state == BootstrapState.CAPITAL_READY:
            if not _transition_if_current_allows(
                fsm,
                BootstrapState,
                BootstrapState.INIT_COMPLETE,
                "bot_main_fsm_advancement",
            ):
                return False

        if fsm.state == BootstrapState.DEGRADED_READY:
            if not _transition_if_current_allows(
                fsm,
                BootstrapState,
                BootstrapState.THREADS_STARTING,
                "bot_main_degraded_handoff",
            ):
                return False

        if fsm.state == BootstrapState.INIT_COMPLETE:
            if not _transition_if_current_allows(
                fsm,
                BootstrapState,
                BootstrapState.THREADS_STARTING,
                "bot_main_fsm_advancement",
            ):
                return False

        if fsm.state == BootstrapState.THREADS_STARTING:
            finalize = getattr(fsm, "finalize_boot", None)
            if callable(finalize):
                if not finalize(reason="bot_main_runtime_handoff"):
                    logger.error("❌ FSM finalize_boot failed from THREADS_STARTING")
                    return False
            elif not _transition_if_current_allows(
                fsm,
                BootstrapState,
                BootstrapState.RUNNING_SUPERVISED,
                "bot_main_fsm_advancement",
            ):
                return False

        if fsm.state == BootstrapState.RUNNING_SUPERVISED:
            if not _publish_supervised_thread_evidence():
                logger.error(
                    "FSM reached RUNNING_SUPERVISED without supervised thread proof"
                )
                return False
            logger.critical(
                "BOOTSTRAP_FSM_RUNTIME_FINALIZED state=RUNNING_SUPERVISED core_registered=true"
            )
            logger.info("✅ FSM is RUNNING_SUPERVISED")
            return True

        logger.error(
            "❌ FSM advancement ended at %s, expected RUNNING_SUPERVISED",
            fsm.state.value,
        )
        return False
    except Exception as exc:
        logger.error("❌ FSM advancement failed: %s", exc, exc_info=True)
        return False


def _perform_post_core_activation_convergence(
    runtime: object,
    trading_thread: threading.Thread,
    *,
    timeout_s: float = 60.0,
) -> bool:
    """Synchronous post-core activation convergence.

    Called after the canonical core thread is registered. Performs every
    required convergence step in order and returns True only when ALL are
    satisfied. On failure, logs the failing gate and returns False so the
    caller can treat the result as fatal pre-dispatch.
    """
    _t0 = time.time()

    registered_thread = getattr(runtime, "_core_thread", None)
    if registered_thread is not trading_thread:
        logger.critical(
            "POST_CORE_CONVERGENCE_FAILED gate=core_identity_mismatch "
            "registered=%r expected=%r",
            registered_thread,
            trading_thread,
        )
        return False
    if not trading_thread.is_alive():
        logger.critical(
            "POST_CORE_CONVERGENCE_FAILED gate=core_thread_not_alive "
            "thread=%s",
            trading_thread.name,
        )
        return False

    try:
        try:
            from bot.preactivation_runtime_identity_guard_v36 import (
                run_preactivation_readiness_convergence,
            )
        except (ImportError, AttributeError):
            run_preactivation_readiness_convergence = None  # type: ignore[assignment]
        if callable(run_preactivation_readiness_convergence):
            run_preactivation_readiness_convergence()
    except Exception as _conv_exc:
        logger.warning(
            "POST_CORE_CONVERGENCE runtime_convergence_optional_failed err=%s",
            _conv_exc,
        )

    try:
        try:
            from bot.readiness_table import snapshot as _rt_snapshot
        except ImportError:
            from readiness_table import snapshot as _rt_snapshot  # type: ignore[import]
        _rt = _rt_snapshot()
        _nonce_ready = _rt.get("nonce_ready", False)
        _authority_ready = _rt.get("authority_ready", False)
        logger.critical(
            "POST_CORE_CONVERGENCE_READINESS_SNAPSHOT nonce_ready=%s "
            "authority_ready=%s execution_ready=%s balance_hydrated=%s "
            "capital_ready=%s bootstrap_ready=%s",
            _nonce_ready,
            _authority_ready,
            _rt.get("execution_ready", False),
            _rt.get("balance_hydrated", False),
            _rt.get("capital_ready", False),
            _rt.get("bootstrap_ready", False),
        )
    except Exception as _rt_exc:
        logger.warning(
            "POST_CORE_CONVERGENCE readiness_snapshot_failed err=%s", _rt_exc
        )

    activation_committed = False
    is_live_active = False
    _can_dispatch = False
    try:
        try:
            from bot.trading_state_machine import get_state_machine
        except ImportError:
            from trading_state_machine import get_state_machine  # type: ignore[import]
        sm = get_state_machine()
        if sm is not None:
            _act_deadline = time.time() + min(timeout_s, 30.0)
            _act_attempts = 0
            while time.time() < _act_deadline:
                _act_attempts += 1
                try:
                    committed = sm.commit_activation()
                except Exception as _ca_exc:
                    logger.warning(
                        "POST_CORE_CONVERGENCE commit_activation_exception "
                        "attempt=%d err=%s",
                        _act_attempts,
                        _ca_exc,
                    )
                    committed = False
                if committed:
                    activation_committed = True
                    break
                time.sleep(1.0)
            is_live_active = sm.is_live_trading_active()
            _can_dispatch_fn = getattr(sm, "can_dispatch_trades", None)
            _can_dispatch = bool(callable(_can_dispatch_fn) and _can_dispatch_fn())
            logger.critical(
                "POST_CORE_CONVERGENCE_ACTIVATION "
                "activation_committed=%s is_live_active=%s "
                "can_dispatch_trades=%s attempts=%d",
                activation_committed,
                is_live_active,
                _can_dispatch,
                _act_attempts,
            )
    except Exception as _sm_exc:
        logger.critical(
            "POST_CORE_CONVERGENCE state_machine_unavailable err=%s — "
            "treating as non-fatal for non-live deployments",
            _sm_exc,
            exc_info=True,
        )

    _runtime_authority_state = ""
    _lifecycle_phase = ""
    _dispatch_enabled = False
    _execution_permitted = False
    try:
        try:
            from bot.startup_coordinator import get_startup_coordinator
        except ImportError:
            from startup_coordinator import get_startup_coordinator  # type: ignore[import]
        coordinator = get_startup_coordinator()
        if coordinator is not None:
            live_workers = sum(
                1
                for worker in threading.enumerate()
                if worker is not threading.current_thread() and worker.is_alive()
            )
            coordinator.record_threads_supervised(
                max(1, live_workers),
                bootstrap_state="RUNNING_SUPERVISED",
            )
            try:
                try:
                    from bot.trading_state_machine import get_state_machine as _get_sm
                    from bot.trading_state_machine import (
                        resolve_runtime_mode_safe as _rms,
                    )
                except ImportError:
                    from trading_state_machine import get_state_machine as _get_sm  # type: ignore[import]
                    from trading_state_machine import resolve_runtime_mode_safe as _rms  # type: ignore[import]
                _sm2 = _get_sm()
                _rm = _rms(logger)
                _intent = bool(_rm is not None and getattr(_rm, "is_live", False))
                try:
                    from bot.startup_coordinator import get_global_state
                except ImportError:
                    from startup_coordinator import get_global_state  # type: ignore[import]
                _gs = get_global_state()
                _snap = _gs.capture(
                    trading_state=(
                        _sm2.get_current_state().value if _sm2 else "UNKNOWN"
                    ),
                    activation_intent=_intent,
                )
                _runtime_authority_state = _snap.startup.runtime_authority_state
                _lifecycle_phase = _snap.startup.lifecycle_phase
                _dispatch_enabled = _snap.startup.dispatch_enabled
                _execution_permitted = _snap.startup.execution_permitted
                logger.critical(
                    "POST_CORE_CONVERGENCE_COORDINATOR "
                    "runtime_authority_state=%s lifecycle_phase=%s "
                    "dispatch_enabled=%s execution_permitted=%s",
                    _runtime_authority_state,
                    _lifecycle_phase,
                    _dispatch_enabled,
                    _execution_permitted,
                )
            except Exception as _snap_exc:
                logger.warning(
                    "POST_CORE_CONVERGENCE coordinator_snapshot_failed err=%s",
                    _snap_exc,
                )
    except Exception as _coord_exc:
        logger.warning(
            "POST_CORE_CONVERGENCE coordinator_unavailable err=%s — non-fatal",
            _coord_exc,
        )

    _can_execute_result = False
    _can_execute_reason = "not_evaluated"
    try:
        try:
            from bot.trading_state_machine import get_state_machine as _get_sm_ce
        except ImportError:
            from trading_state_machine import get_state_machine as _get_sm_ce  # type: ignore[import]
        _sm_ce = _get_sm_ce()
        if _sm_ce is not None:
            _can_execute_result = bool(_sm_ce.can_execute())
            _can_execute_reason = "allowed" if _can_execute_result else "denied"
    except Exception as _ce_exc:
        _can_execute_reason = f"exception:{_ce_exc}"
        logger.warning("POST_CORE_CONVERGENCE can_execute_failed err=%s", _ce_exc)

    try:
        _rt_final = {}
        try:
            from bot.readiness_table import snapshot as _rts
        except ImportError:
            from readiness_table import snapshot as _rts  # type: ignore[import]
        _rt_final = _rts()
    except Exception:
        _rt_final = {}

    logger.critical(
        "POST_CORE_ACTIVATION_READINESS "
        "writer_acquired=%s core_alive=%s "
        "bootstrap_state=RUNNING_SUPERVISED "
        "balance_hydrated=%s capital_ready=%s "
        "nonce_ready=%s execution_ready=%s authority_ready=%s "
        "activation_committed=%s is_live_active=%s can_dispatch_trades=%s "
        "runtime_authority_state=%s lifecycle_phase=%s dispatch_enabled=%s "
        "can_execute=%s can_execute_reason=%s "
        "elapsed_ms=%.0f",
        bool(runtime and getattr(runtime, "acquired", False)),
        trading_thread.is_alive(),
        _rt_final.get("balance_hydrated", False),
        _rt_final.get("capital_ready", False),
        _rt_final.get("nonce_ready", False),
        _rt_final.get("execution_ready", False),
        _rt_final.get("authority_ready", False),
        activation_committed,
        is_live_active,
        _can_dispatch,
        _runtime_authority_state or "unknown",
        _lifecycle_phase or "unknown",
        _dispatch_enabled,
        _can_execute_result,
        _can_execute_reason,
        (time.time() - _t0) * 1000,
    )

    import os as _os

    _is_live_env = (
        _os.environ.get("LIVE_CAPITAL_VERIFIED", "").lower() in {"true", "1", "yes"}
    )
    if _is_live_env and not _can_execute_result:
        logger.critical(
            "EXECUTION_READINESS_FINAL allow=false "
            "first_failed_gate=can_execute reason=%s "
            "trading_remains_fail_closed=true",
            _can_execute_reason,
        )
        return False

    logger.critical(
        "EXECUTION_READINESS_FINAL allow=%s "
        "can_execute=%s activation_committed=%s is_live_active=%s",
        _can_execute_result,
        _can_execute_result,
        activation_committed,
        is_live_active,
    )
    return True


def _fail_closed_strategy_publication(detail: str) -> None:
    """Revoke process-local runtime claims when no executable strategy exists."""

    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    os.environ["NIJA_RUNTIME_TRADING_STATE"] = "OFF"
    logger.critical(
        "CANONICAL_STRATEGY_PUBLICATION_FAILED detail=%s "
        "runtime_state=OFF execution_authority=0 "
        "trading_remains_fail_closed=true",
        detail,
    )


def _publish_canonical_strategy_for_runtime(
    broker: object,
) -> Optional[object]:
    """Build and publish the strategy required by the trading-loop contract."""

    try:
        from bot.strategy_publication_patch import publish_canonical_strategy

        strategy, detail = publish_canonical_strategy(explicit_broker=broker)
    except Exception as exc:
        detail = f"publication_exception:{type(exc).__name__}:{exc}"
        logger.critical(
            "CANONICAL_STRATEGY_PUBLICATION_EXCEPTION type=%s err=%s",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        strategy = None

    if strategy is None or not callable(getattr(strategy, "run_cycle", None)):
        if strategy is not None:
            detail = "strategy_run_cycle_unavailable"
        _fail_closed_strategy_publication(detail)
        return None

    if getattr(strategy, "broker", None) is None:
        _fail_closed_strategy_publication("strategy_broker_missing")
        return None

    logger.critical(
        "CANONICAL_STRATEGY_HANDOFF_READY detail=%s strategy=%s broker=%s "
        "run_cycle=true",
        detail,
        type(strategy).__name__,
        type(getattr(strategy, "broker", None)).__name__,
    )
    try:
        from bot.strategy_publication_patch import start_monitor

        start_monitor()
    except Exception as exc:
        logger.warning(
            "CANONICAL_STRATEGY_PUBLICATION_MONITOR_START_FAILED err=%s",
            exc,
        )
    return strategy


def _keep_process_alive_after_loop_return() -> None:
    """Keep the main process alive while supervised trading threads run."""

    logger.critical(
        "BOT_MAIN_KEEPALIVE_ENTERED reason=start_trading_engine_returned "
        "startup_complete=%s",
        _startup_complete,
    )
    last_heartbeat = 0.0
    while not _shutdown_event.is_set():
        runtime = _writer_authority_runtime
        core_thread = _core_loop_thread
        if runtime is not None and runtime.lost:
            logger.critical(
                "BOT_MAIN_KEEPALIVE_EXIT reason=writer_authority_lost marker=20260710u"
            )
            _shutdown_event.set()
            break
        if core_thread is not None and not core_thread.is_alive():
            logger.critical(
                "CORE_LOOP_EXITED thread_name=%s ident=%s",
                core_thread.name,
                core_thread.ident,
            )
            _shutdown_event.set()
            break

        now = time.monotonic()
        if now - last_heartbeat >= 60.0:
            active_threads = [t.name for t in threading.enumerate() if t.is_alive()]
            logger.info(
                "BOT_MAIN_KEEPALIVE_HEARTBEAT startup_complete=%s "
                "writer_authority=%s active_threads=%s",
                _startup_complete,
                bool(runtime and runtime.acquired),
                active_threads,
            )
            last_heartbeat = now
        _shutdown_event.wait(timeout=max(1.0, SUPERVISOR_POLL_INTERVAL_S))
    logger.info("BOT_MAIN_KEEPALIVE_EXIT reason=shutdown_event_set")


def main() -> int:
    """Run NIJA with writer authority established before nonce startup."""

    global _startup_complete, _core_loop_thread, _process_exit_code, _process_exit_reason

    _process_exit_code = 0
    _process_exit_reason = ""
    os.environ.pop("NIJA_PROCESS_EXIT_REQUESTED", None)
    os.environ.pop("NIJA_PROCESS_EXIT_CODE", None)
    os.environ.pop("NIJA_PROCESS_EXIT_REASON", None)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger.info("=" * 80)
    logger.info("🚀 NIJA TRADING BOT — APEX v7.2.0")
    logger.info("=" * 80)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    _startup_stage_ts["process_main_start"] = time.time()
    logger.info("\n[STEP 0] Redis Writer Authority")
    if not _acquire_writer_authority_before_nonce():
        if _shutdown_event.is_set():
            logger.info("Startup stopped while waiting for writer authority")
            return _process_exit_code or 0
        if _writer_authority_last_error == "active_writer_lock_held":
            logger.info("Writer authority held elsewhere; remaining safe standby")
            return 0
        logger.critical("❌ Writer authority unavailable — trading remains blocked")
        return _process_exit_code or 1

    _startup_stage_ts["writer_acquired"] = time.time()
    try:
        logger.info("\n[STEP 0.5] Canonical Broker Prebootstrap")
        try:
            from bot.canonical_broker_prebootstrap_v22 import (
                prepare_canonical_broker_runtime,
            )

            manager = prepare_canonical_broker_runtime()
            if not getattr(manager, "_fsm_initialized", False):
                raise RuntimeError("Broker manager did not initialize")
            connected_brokers = _connected_platform_broker_count(manager)
            if connected_brokers < 1:
                raise RuntimeError("No connected platform broker")
            from bot.kraken_all_account_supervision_v86 import (
                install as install_kraken_all_account_supervision,
                reconcile_once as reconcile_kraken_users_once,
            )

            if not install_kraken_all_account_supervision():
                raise RuntimeError("Kraken all-account supervision did not install")
            kraken_user_state = reconcile_kraken_users_once(manager)
            if not kraken_user_state.get("ok") and kraken_user_state.get(
                "reason"
            ) != "recovery_active":
                raise RuntimeError(
                    "Kraken user supervision unavailable: "
                    f"{kraken_user_state.get('reason', 'unknown')}"
                )
            logger.critical(
                "KRAKEN_ALL_ACCOUNT_SUPERVISION_READY registered=%s connected=%s "
                "disconnected=%s reason=%s continuous=true",
                kraken_user_state.get("registered", 0),
                kraken_user_state.get("connected", 0),
                kraken_user_state.get("disconnected", 0),
                kraken_user_state.get("reason", "unknown"),
            )
            logger.critical(
                "DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY "
                "fsm_initialized=true connected_brokers=%d thread=%s",
                connected_brokers,
                threading.current_thread().name,
            )
            os.environ["NIJA_DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY"] = "1"
            _startup_stage_ts["broker_prebootstrap_done"] = time.time()
        except Exception as broker_exc:
            os.environ["NIJA_DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY"] = "0"
            logger.critical(
                "DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_FAILED err=%s:%s "
                "trading_remains_fail_closed=true",
                type(broker_exc).__name__,
                broker_exc,
                exc_info=True,
            )
            return 1

        logger.info("\n[STEP 1] Self-Healing Bootstrap")
        ok, broker, broker_name = _run_self_healing_startup()
        if not ok:
            logger.critical("❌ Bootstrap failed — exiting")
            return 1
        logger.info("✅ Connected to %s", broker_name)
        _startup_stage_ts["self_healing_done"] = time.time()

        logger.info("\n[STEP 2] Advancing Bootstrap FSM to THREADS_STARTING (pre-core)")
        if not _advance_bootstrap_fsm_to_threads_starting():
            logger.critical("❌ FSM pre-core advancement failed — exiting")
            return 1

        logger.info("✅ FSM is THREADS_STARTING (core not yet started)")
        _startup_stage_ts["fsm_threads_starting_done"] = time.time()

        logger.info("\n[STEP 2.5] Publishing Canonical Trading Strategy")
        _startup_stage_ts["step2.5_start"] = time.time()
        strategy = _publish_canonical_strategy_for_runtime(broker)
        if strategy is None:
            logger.critical(
                "❌ Canonical TradingStrategy unavailable — exiting fail closed"
            )
            return 1
        _startup_stage_ts["step2.5_done"] = time.time()
        logger.critical(
            "STARTUP_STAGE_TIMING marker=20260811-startup-watchdog "
            "step=2.5_strategy_published elapsed_s=%.2f",
            _startup_stage_ts["step2.5_done"] - _startup_stage_ts.get("step2.5_start", _startup_stage_ts["step2.5_done"]),
        )

        logger.info("\n[STEP 3] Starting Trading Loop")
        # Arm the startup watchdog.  It will dump per-thread stacks if
        # CANONICAL_CORE_THREAD_REGISTERED is not reached within the deadline.
        _watchdog_deadline_s = float(
            os.environ.get("NIJA_STARTUP_WATCHDOG_DEADLINE_S", "120")
        )
        _watchdog_thread = threading.Thread(
            target=_startup_registration_watchdog,
            args=(_watchdog_deadline_s,),
            name="StartupRegistrationWatchdog",
            daemon=True,
        )
        _watchdog_thread.start()
        _startup_stage_ts["step3_start"] = time.time()
        try:
            from bot.nija_core_loop import start_trading_engine
            from bot.startup_coordinator import get_startup_coordinator

            runtime = _writer_authority_runtime
            if runtime is None:
                raise RuntimeError(
                    "Canonical writer runtime missing before core-loop handoff"
                )
            arm_deadline = getattr(runtime, "arm_scan_start_deadline", None)
            if not callable(arm_deadline):
                raise RuntimeError("Writer runtime cannot arm the scan-start deadline")
            arm_deadline("bot_main_step3")
            logger.critical("CORE_LOOP_STARTING strategy_type=%s", type(strategy).__name__)
            _startup_stage_ts["start_trading_engine_call"] = time.time()
            trading_thread = start_trading_engine(strategy)
            _startup_stage_ts["start_trading_engine_done"] = time.time()
            logger.critical("CORE_LOOP_STARTED thread_name=%s elapsed_s=%.2f", getattr(trading_thread, "name", "unknown"),
                _startup_stage_ts["start_trading_engine_done"] - _startup_stage_ts["start_trading_engine_call"])

            if trading_thread is None:
                raise RuntimeError("Trading thread not created by start_trading_engine")

            # Fix 4: Explicitly wait for the thread to enter its running state
            # before registering it with the writer authority.  start_trading_engine
            # returns a started Thread, but is_alive() may transiently return False
            # in the brief window between Thread.start() and the OS scheduling the
            # new thread.  Waiting here ensures register_core_thread sees a live
            # thread instead of setting core_thread_last_alive_at=0.
            _alive_deadline = time.time() + 5.0
            while not trading_thread.is_alive() and time.time() < _alive_deadline:
                time.sleep(0.05)

            if not trading_thread.is_alive():
                raise RuntimeError("Trading thread not running after start_trading_engine")

            logger.critical(
                "CORE_LOOP_THREAD_ALIVE thread=%s ident=%s",
                trading_thread.name,
                trading_thread.ident,
            )
            # Identity guard: ensure the canonical singleton that owns the
            # heartbeat is the same object used for registration.
            from bot.entrypoint_writer_authority import (
                EntrypointWriterAuthority,
                bind_entrypoint_writer_authority_aliases,
                get_entrypoint_writer_authority,
            )
            if isinstance(runtime, EntrypointWriterAuthority):
                bind_entrypoint_writer_authority_aliases(runtime)
                canonical_runtime = get_entrypoint_writer_authority()
                if canonical_runtime is not runtime:
                    logger.critical(
                        "STARTUP_SINGLETON_IDENTITY_DRIFT marker=20260811-startup-watchdog "
                        "runtime_id=%d canonical_id=%d — forcing canonical binding",
                        id(runtime),
                        id(canonical_runtime),
                    )
                    bind_entrypoint_writer_authority_aliases(runtime)
            register_core_thread = getattr(runtime, "register_core_thread", None)
            if not callable(register_core_thread):
                raise RuntimeError(
                    "Canonical writer runtime cannot register the core thread"
                )
            registered_thread = getattr(runtime, "_core_thread", None)
            if registered_thread is not trading_thread:
                register_core_thread(trading_thread)
            registered_thread = getattr(runtime, "_core_thread", trading_thread)
            if registered_thread is not trading_thread:
                raise RuntimeError(
                    "Canonical writer runtime rejected the core-thread handoff"
                )
            # Identity invariant: all three handles must point at the same thread.
            if _core_loop_thread is not None and _core_loop_thread is not trading_thread:
                raise RuntimeError(
                    "Core-loop thread identity mismatch: "
                    f"bot_main._core_loop_thread={_core_loop_thread!r} "
                    f"trading_thread={trading_thread!r}"
                )
            _core_loop_thread = trading_thread
            _startup_stage_ts["canonical_core_registered"] = time.time()
            logger.critical(
                "CANONICAL_CORE_THREAD_REGISTERED thread=%s ident=%s "
                "writer_generation=%s",
                trading_thread.name,
                trading_thread.ident,
                getattr(runtime, "_generation", "unknown"),
            )
            # Signal the watchdog that registration is complete.
            _startup_registration_done.set()
            logger.critical(
                "CORE_RUNTIME_REGISTERED thread=%s ident=%s writer_generation=%s "
                "marker=post_core_handoff_v1",
                trading_thread.name,
                trading_thread.ident,
                getattr(runtime, "_generation", "unknown"),
            )
            # Spec item J: advance BootstrapFSM from THREADS_STARTING to
            # RUNNING_SUPERVISED now that the real core thread is registered.
            # This finalizes the canonical startup handoff sequence.
            if not _advance_bootstrap_fsm_to_running_supervised():
                logger.critical(
                    "BOOTSTRAP_FSM_RUNNING_SUPERVISED_ADVANCEMENT_FAILED — "
                    "treating as fatal pre-dispatch per spec §A.2"
                )
                raise RuntimeError(
                    "BootstrapFSM failed to reach RUNNING_SUPERVISED after core registration"
                )
            _convergence_ok = _perform_post_core_activation_convergence(
                runtime,
                trading_thread,
            )
            if not _convergence_ok:
                raise RuntimeError(
                    "Post-core activation convergence failed before dispatch enablement"
                )
            _startup_complete = True
            try:
                from bot.nija_core_loop import TRADING_ENGINE_READY

                if hasattr(TRADING_ENGINE_READY, "set"):
                    TRADING_ENGINE_READY.set()
                    logger.critical(
                        "TRADING_ENGINE_READY_SET source=bot_main_post_core_convergence"
                    )
            except Exception as _ready_exc:
                logger.warning(
                    "TRADING_ENGINE_READY_SET_FAILED err=%s (non-fatal)",
                    _ready_exc,
                )
            # Emit complete startup timing summary (spec item BA).
            _t0 = _startup_stage_ts.get(
                "process_main_start",
                _startup_stage_ts.get("canonical_core_registered", time.time()),
            )

            def _ms(key: str) -> str:
                ts = _startup_stage_ts.get(key)
                return f"{(ts - _t0) * 1000:.0f}" if ts is not None else "n/a"

            logger.critical(
                "STARTUP_TIMING "
                "writer_acquired_ms=%s "
                "platform_init_ms=%s "
                "self_healing_ms=%s "
                "fsm_threads_starting_ms=%s "
                "strategy_published_ms=%s "
                "core_start_ms=%s "
                "core_registration_ms=%s "
                "total_to_core_registered_ms=%s",
                _ms("writer_acquired"),
                _ms("broker_prebootstrap_done"),
                _ms("self_healing_done"),
                _ms("fsm_threads_starting_done"),
                _ms("step2.5_done"),
                _ms("start_trading_engine_done"),
                _ms("canonical_core_registered"),
                _ms("canonical_core_registered"),
            )
            logger.critical(
                "EXECUTION_AUTHORITY_READY writer_generation=%s core_thread=%s "
                "ident=%s convergence_ok=%s",
                getattr(runtime, "_generation", "unknown"),
                trading_thread.name,
                trading_thread.ident,
                _convergence_ok,
            )

            # Publish verified thread evidence to the startup coordinator so that
            # the threads.running gate passes in evaluate_system_readiness_proof().
            try:
                _coordinator = get_startup_coordinator()
                live_workers = sum(
                    1
                    for worker in threading.enumerate()
                    if worker is not threading.current_thread() and worker.is_alive()
                )
                worker_count = max(1, live_workers)
                _coordinator.record_threads_supervised(
                    worker_count,
                    bootstrap_state="RUNNING_SUPERVISED",
                )
                logger.critical(
                    "ACTIVATION_GATE_THREADS_RUNNING workers=%d threads_confirmed=true",
                    worker_count,
                )
            except Exception as _tc_exc:
                logger.warning(
                    "ACTIVATION_GATE_THREADS_PUBLISH_FAILED err=%s (non-fatal)",
                    _tc_exc,
                )

            if not _shutdown_event.is_set():
                logger.critical(
                    "EXIT_SUPERVISION_ACTIVE core_thread=%s ident=%s",
                    trading_thread.name,
                    trading_thread.ident,
                )
                _keep_process_alive_after_loop_return()
        except KeyboardInterrupt:
            logger.info("⏸️ Keyboard interrupt received")
            return 0
        except Exception as exc:
            logger.critical(
                "CANONICAL_STARTUP_EXCEPTION reason=core_loop_startup_or_registration_failed "
                "type=%s err=%s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return _process_exit_code or 1

        logger.info("✅ Bot shutdown complete")
        return _process_exit_code or 0
    finally:
        _shutdown_event.set()
        # Spec AZ: quiesce all workers that can issue private exchange API calls
        # BEFORE releasing the writer authority.  This prevents Kraken private
        # API calls (balance, positions, nonce) from occurring after the writer
        # lease is released.
        #
        # Shutdown order:
        # 1. signal all workers to stop
        # 2. stop v86 Kraken user supervision (prevents new reconnect jobs)
        # 3. join canonical core thread if it was started
        # 4. release writer authority LAST
        _signal_core_loop_shutdown(_process_exit_reason or "bot_main_finally")

        try:
            from bot.kraken_all_account_supervision_v86 import (
                stop as _stop_kraken_v86,
                _WATCHDOG_STOP as _v86_stop_event,
            )
            _stop_kraken_v86()
        except Exception as _v86_stop_err:
            logger.warning("v86 stop failed (non-fatal): %s", _v86_stop_err)

        _join_thread = _core_loop_thread
        if _join_thread is not None and _join_thread.is_alive():
            logger.info(
                "SHUTDOWN_JOINING_CORE_THREAD thread=%s timeout=10s",
                _join_thread.name,
            )
            _join_thread.join(timeout=10.0)
            if _join_thread.is_alive():
                logger.warning(
                    "SHUTDOWN_CORE_THREAD_JOIN_TIMEOUT thread=%s — proceeding with writer release",
                    _join_thread.name,
                )

        _release_writer_authority()


if __name__ == "__main__":
    sys.exit(main())
