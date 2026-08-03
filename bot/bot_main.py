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


def _signal_handler(signum: int, frame) -> None:
    """Handle SIGTERM/SIGINT without granting or retaining stale authority."""

    sig_name = signal.Signals(signum).name
    logger.critical("🛑 Received signal %s — initiating graceful shutdown", sig_name)
    _shutdown_event.set()


def _acquire_writer_authority_before_nonce() -> bool:
    """Establish Redis fencing lineage before any nonce-manager access."""

    global _writer_authority_runtime, _authority_heartbeat_monitor, _writer_authority_last_error

    try:
        from bot.entrypoint_writer_authority import get_entrypoint_writer_authority

        runtime = get_entrypoint_writer_authority()
        result = runtime.acquire_with_standby(shutdown_event=_shutdown_event)
        _writer_authority_last_error = str(getattr(result, "error", "") or "")
        if not result.acquired:
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

    global _startup_complete, _core_loop_thread

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger.info("=" * 80)
    logger.info("🚀 NIJA TRADING BOT — APEX v7.2.0")
    logger.info("=" * 80)

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    logger.info("\n[STEP 0] Redis Writer Authority")
    if not _acquire_writer_authority_before_nonce():
        if _shutdown_event.is_set():
            logger.info("Startup stopped while waiting for writer authority")
            return 0
        if _writer_authority_last_error == "active_writer_lock_held":
            logger.info("Writer authority held elsewhere; remaining safe standby")
            return 0
        logger.critical("❌ Writer authority unavailable — trading remains blocked")
        return 1

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
            logger.critical(
                "DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY "
                "fsm_initialized=true connected_brokers=%d thread=%s",
                connected_brokers,
                threading.current_thread().name,
            )
            os.environ["NIJA_DIRECT_CANONICAL_BROKER_PREBOOTSTRAP_V27_READY"] = "1"
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

        logger.info("\n[STEP 2] Advancing Bootstrap FSM")
        if not _advance_bootstrap_fsm_to_running_supervised():
            logger.critical("❌ FSM advancement failed — exiting")
            return 1

        logger.info("✅ FSM is RUNNING_SUPERVISED")

        logger.info("\n[STEP 2.5] Publishing Canonical Trading Strategy")
        strategy = _publish_canonical_strategy_for_runtime(broker)
        if strategy is None:
            logger.critical(
                "❌ Canonical TradingStrategy unavailable — exiting fail closed"
            )
            return 1
        _startup_complete = True

        logger.info("\n[STEP 3] Starting Trading Loop")
        try:
            from bot.nija_core_loop import start_trading_engine
            from bot.startup_coordinator import get_startup_coordinator

            logger.critical("CORE_LOOP_STARTING strategy_type=%s", type(strategy).__name__)
            trading_thread = start_trading_engine(strategy)
            logger.critical("CORE_LOOP_STARTED thread_name=%s", getattr(trading_thread, "name", "unknown"))
            _core_loop_thread = trading_thread

            if trading_thread is None:
                raise RuntimeError("Trading thread not created by start_trading_engine")
            if not trading_thread.is_alive():
                raise RuntimeError("Trading thread not running after start_trading_engine")

            logger.critical(
                "CORE_LOOP_THREAD_ALIVE thread=%s ident=%s",
                trading_thread.name,
                trading_thread.ident,
            )
            runtime = _writer_authority_runtime
            if runtime is not None and callable(getattr(runtime, "register_core_thread", None)):
                runtime.register_core_thread(trading_thread)

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
                _keep_process_alive_after_loop_return()
        except KeyboardInterrupt:
            logger.info("⏸️ Keyboard interrupt received")
            return 0
        except Exception as exc:
            logger.critical(
                "❌ Trading loop exception: %s: %s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return 1

        logger.info("✅ Bot shutdown complete")
        return 0
    finally:
        _shutdown_event.set()
        _release_writer_authority()


if __name__ == "__main__":
    sys.exit(main())
