#!/usr/bin/env python3
"""
NIJA Trading Bot — Main Entry Point (APEX v7.2.0)
==================================================

Complete trading bot with self-healing bootstrap, multi-broker support,
and deterministic execution authority.

Entry point: python -m bot.bot_main
or:         python bot/bot_main.py

Architecture
------------
1. SelfHealingStartup   — resilient broker connection with fallback
2. BootstrapFSM         — composite state machine (19 states)
3. TradingStrategy      — APEX v7.2.0 with multi-account support
4. NijaCoreLoop         — main trading cycle with cycle scheduler
5. SupervisorLoop       — watchdog and restart logic

Author: NIJA Trading Systems
Version: 7.2.0
Date: June 2026
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

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

# Bootstrap timeout (seconds) — maximum time to wait for each startup phase
BOOTSTRAP_TIMEOUT_S = float(os.environ.get("NIJA_BOOTSTRAP_TIMEOUT_S", "300"))

# Supervisor poll interval (seconds) — how often to check trading loop health
SUPERVISOR_POLL_INTERVAL_S = float(os.environ.get("NIJA_SUPERVISOR_POLL_S", "10"))

# Maximum consecutive supervisor failures before hard restart request
SUPERVISOR_MAX_FAILURES = int(os.environ.get("NIJA_SUPERVISOR_MAX_FAILURES", "3"))


# ─────────────────────────────────────────────────────────────────────────────
# Global state
# ─────────────────────────────────────────────────────────────────────────────

_shutdown_event = threading.Event()
_startup_complete = False


# ─────────────────────────────────────────────────────────────────────────────
# Signal handlers
# ─────────────────────────────────────────────────────────────────────────────

def _signal_handler(signum: int, frame) -> None:
    """Handle SIGTERM/SIGINT gracefully."""
    sig_name = signal.Signals(signum).name
    logger.critical(f"🛑 Received signal {sig_name} — initiating graceful shutdown")
    _shutdown_event.set()


# ─────────────────────────────────────────────────────────────────────────────
# Bootstrap orchestration
# ─────────────────────────────────────────────────────────────────────────────

def _run_self_healing_startup() -> tuple[bool, Optional[object], str]:
    """
    Run the self-healing startup sequence.

    Returns:
        (success, broker, broker_name)
    """
    logger.info("🚀 Starting self-healing bootstrap sequence...")

    try:
        from bot.self_healing_startup import SelfHealingStartup, StartupConfig

        config = StartupConfig()
        startup = SelfHealingStartup(config)
        result = startup.run()

        if result.ok:
            logger.info(f"✅ Bootstrap complete: broker={result.broker_name} mode={'FALLBACK' if result.on_fallback else 'PRIMARY'}")
            return True, result.broker, result.broker_name
        else:
            logger.critical(f"❌ Bootstrap failed: {result.reason}")
            return False, None, ""

    except Exception as e:
        logger.critical(f"❌ Bootstrap exception: {type(e).__name__}: {e}", exc_info=True)
        return False, None, ""


def _transition_if_current_allows(fsm, BootstrapState, target, reason: str) -> bool:
    """Apply one legal transition when the current FSM state is directly before target."""

    if fsm.state == target:
        return True
    ok = fsm.transition(target, reason=reason)
    if ok:
        logger.info("✅ FSM → %s", target.value)
    return bool(ok)


def _advance_bootstrap_fsm_to_running_supervised() -> bool:
    """Advance BootstrapFSM to RUNNING_SUPERVISED using only legal FSM transitions."""
    logger.info("🚀 Advancing bootstrap FSM to RUNNING_SUPERVISED...")

    try:
        from bot.bootstrap_state_machine import get_bootstrap_fsm, BootstrapState

        fsm = get_bootstrap_fsm()

        if fsm.state == BootstrapState.RUNNING_SUPERVISED:
            logger.info("✅ FSM already RUNNING_SUPERVISED")
            return True

        fsm.claim_bootstrap_ownership()
        logger.info("BootstrapFSM pre-handoff state=%s", fsm.state.value)

        # SelfHealingStartup may leave the composite BootstrapFSM at an earlier
        # legal state such as LOCK_ACQUIRED after broker/capital startup has
        # already succeeded. Do not jump directly to INIT_COMPLETE: the FSM
        # explicitly requires LOCK_ACQUIRED -> HEALTH_BOUND -> ... ->
        # CAPITAL_READY -> INIT_COMPLETE. Use its own happy-path helper first.
        if fsm.state not in {
            BootstrapState.CAPITAL_READY,
            BootstrapState.INIT_COMPLETE,
            BootstrapState.DEGRADED_READY,
            BootstrapState.THREADS_STARTING,
            BootstrapState.RUNNING_SUPERVISED,
        }:
            advance_to_capital_ready = getattr(fsm, "advance_to_capital_ready", None)
            if callable(advance_to_capital_ready):
                if not advance_to_capital_ready(reason="bot_main_post_self_healing_startup"):
                    logger.error(
                        "❌ FSM advance_to_capital_ready failed; current_state=%s",
                        fsm.state.value,
                    )
                    return False
            else:
                logger.error(
                    "❌ FSM cannot advance legally from %s; advance_to_capital_ready unavailable",
                    fsm.state.value,
                )
                return False

        # Complete final handoff using the legal tail of the FSM.
        if fsm.state == BootstrapState.CAPITAL_READY:
            if not _transition_if_current_allows(
                fsm,
                BootstrapState,
                BootstrapState.INIT_COMPLETE,
                "bot_main_fsm_advancement",
            ):
                logger.error("❌ FSM transition to INIT_COMPLETE failed from %s", fsm.state.value)
                return False

        if fsm.state == BootstrapState.DEGRADED_READY:
            if not _transition_if_current_allows(
                fsm,
                BootstrapState,
                BootstrapState.THREADS_STARTING,
                "bot_main_degraded_handoff",
            ):
                logger.error("❌ FSM transition from DEGRADED_READY to THREADS_STARTING failed")
                return False

        if fsm.state == BootstrapState.INIT_COMPLETE:
            if not _transition_if_current_allows(
                fsm,
                BootstrapState,
                BootstrapState.THREADS_STARTING,
                "bot_main_fsm_advancement",
            ):
                logger.error("❌ FSM transition to THREADS_STARTING failed from %s", fsm.state.value)
                return False

        if fsm.state == BootstrapState.THREADS_STARTING:
            finalize_boot = getattr(fsm, "finalize_boot", None)
            if callable(finalize_boot):
                if not finalize_boot(reason="bot_main_runtime_handoff"):
                    logger.error("❌ FSM finalize_boot failed from THREADS_STARTING")
                    return False
            else:
                if not _transition_if_current_allows(
                    fsm,
                    BootstrapState,
                    BootstrapState.RUNNING_SUPERVISED,
                    "bot_main_fsm_advancement",
                ):
                    logger.error("❌ FSM transition to RUNNING_SUPERVISED failed")
                    return False

        if fsm.state == BootstrapState.RUNNING_SUPERVISED:
            logger.info("✅ FSM is RUNNING_SUPERVISED")
            return True

        logger.error("❌ FSM advancement ended at %s, expected RUNNING_SUPERVISED", fsm.state.value)
        return False

    except Exception as e:
        logger.error(f"❌ FSM advancement failed: {e}", exc_info=True)
        return False


def _keep_process_alive_after_loop_return() -> None:
    """Keep Railway process alive when the trading loop is already running.

    Some runtime patches correctly avoid spawning a duplicate trading loop and
    return immediately from ``start_trading_engine`` with a log line such as
    "Trading loop already active; skipping duplicate thread spawn".  The main
    process must not treat that successful no-op as shutdown, otherwise atexit
    releases the writer lock and Railway restarts the container.
    """

    logger.critical(
        "BOT_MAIN_KEEPALIVE_ENTERED reason=start_trading_engine_returned startup_complete=%s",
        _startup_complete,
    )
    last_heartbeat = 0.0
    while not _shutdown_event.is_set():
        now = time.monotonic()
        if now - last_heartbeat >= 60.0:
            active_threads = [t.name for t in threading.enumerate() if t.is_alive()]
            logger.info(
                "BOT_MAIN_KEEPALIVE_HEARTBEAT startup_complete=%s active_threads=%s",
                _startup_complete,
                active_threads,
            )
            last_heartbeat = now
        _shutdown_event.wait(timeout=max(1.0, SUPERVISOR_POLL_INTERVAL_S))
    logger.info("BOT_MAIN_KEEPALIVE_EXIT reason=shutdown_event_set")


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    """Main entry point for the NIJA trading bot."""
    global _startup_complete

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    logger.info("=" * 80)
    logger.info("🚀 NIJA TRADING BOT — APEX v7.2.0")
    logger.info("=" * 80)

    # Register signal handlers
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # Step 1: Self-healing bootstrap
    logger.info("\n[STEP 1] Self-Healing Bootstrap")
    ok, broker, broker_name = _run_self_healing_startup()
    if not ok:
        logger.critical("❌ Bootstrap failed — exiting")
        return 1

    logger.info(f"✅ Connected to {broker_name}")

    # Step 2: Advance FSM to RUNNING_SUPERVISED
    logger.info("\n[STEP 2] Advancing Bootstrap FSM")
    ok = _advance_bootstrap_fsm_to_running_supervised()
    if not ok:
        logger.critical("❌ FSM advancement failed — exiting")
        return 1

    logger.info("✅ FSM is RUNNING_SUPERVISED")
    _startup_complete = True

    # Step 3: Start trading loop
    logger.info("\n[STEP 3] Starting Trading Loop")
    try:
        from bot.nija_core_loop import start_trading_engine

        logger.info("🎯 Entering trading loop...")
        start_trading_engine(broker)

        # If start_trading_engine returns without an explicit shutdown signal, the
        # trading loop is usually already active in a background thread. Keep the
        # main process alive so atexit does not release writer authority.
        if not _shutdown_event.is_set():
            _keep_process_alive_after_loop_return()

    except KeyboardInterrupt:
        logger.info("⏸️  Keyboard interrupt received")
        return 0

    except Exception as e:
        logger.critical(f"❌ Trading loop exception: {type(e).__name__}: {e}", exc_info=True)
        return 1

    finally:
        _shutdown_event.set()

    logger.info("✅ Bot shutdown complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
