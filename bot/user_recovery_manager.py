"""
USER RECOVERY MANAGER
=====================

Orchestrates a safe, orderly wind-down of all user trading activity:

1. Stop opening new trades (active_trading flag = false in user config)
2. Force-close all existing user positions via ForcedPositionCleanup
3. Cancel all open orders for each user account
4. Verify user balances are fully available (100 % cash)

The manager runs the forced-cleanup loop every 60 seconds until all positions
are closed, then confirms each user's balance is liquid.

Usage (from trading_strategy or a management script):
    from bot.user_recovery_manager import UserRecoveryManager

    manager = UserRecoveryManager(multi_account_manager)
    manager.start_recovery()          # non-blocking – runs in a background thread
    ...
    summary = manager.get_status()    # check progress at any time
    manager.stop_recovery()           # graceful shutdown
"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

logger = logging.getLogger("nija.user_recovery")

# How often the cleanup loop runs (seconds)
CLEANUP_INTERVAL_SECONDS = 60

# How often the balance monitor polls (seconds)
BALANCE_POLL_INTERVAL_SECONDS = 300  # 5 minutes

# Minimum funded balance threshold (mirrors independent_broker_trader)
MINIMUM_FUNDED_BALANCE = 0.50


class UserRecoveryManager:
    """
    Manages the full recovery sequence for user accounts:
      1. Block new trade entries (active_trading check in the trading loop)
      2. Force-close all positions via ForcedPositionCleanup (every 60 s)
      3. Cancel all open orders
      4. Monitor and report user balances

    The cleanup engine already exists in ForcedPositionCleanup; this class
    wires it to the multi-account manager and drives the recovery loop.
    """

    def __init__(self, multi_account_manager):
        """
        Args:
            multi_account_manager: MultiAccountBrokerManager instance that owns
                                   all user broker connections.
        """
        self.multi_account_manager = multi_account_manager

        self._stop_event = threading.Event()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._balance_thread: Optional[threading.Thread] = None

        # Recovery status tracking
        self._status: Dict[str, Any] = {
            'started_at': None,
            'cleanup_cycles': 0,
            'last_cleanup_at': None,
            'users': {},
        }
        self._status_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start_recovery(self) -> None:
        """
        Begin the recovery sequence in background threads.

        Step 1 (blocking, immediate): Log that active_trading=false is enforced
                                      by the trading loop – no code change needed
                                      here; the flag is read from user config.
        Step 2 (background thread):   Run ForcedPositionCleanup every 60 s.
        Step 3 (handled by cleanup):  cancel_open_orders=True is passed to
                                      ForcedPositionCleanup so every cleanup
                                      sweep also cancels pending orders.
        Step 4 (background thread):   Balance monitor logs available cash every
                                      BALANCE_POLL_INTERVAL_SECONDS seconds.
        """
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            logger.warning("⚠️  UserRecoveryManager already running – ignoring duplicate start()")
            return

        self._stop_event.clear()

        with self._status_lock:
            self._status['started_at'] = datetime.now(timezone.utc).isoformat()
            self._status['cleanup_cycles'] = 0

        logger.warning("=" * 70)
        logger.warning("🔴 USER RECOVERY MODE ACTIVATED")
        logger.warning("=" * 70)
        logger.warning("   Step 1: New trade entries BLOCKED (active_trading=false)")
        logger.warning("   Step 2: Forced position cleanup will run every 60 s")
        logger.warning("   Step 3: Open orders cancelled on every cleanup sweep")
        logger.warning("   Step 4: Balance monitor running every 5 min")
        logger.warning("=" * 70)

        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="UserRecovery-Cleanup",
            daemon=True,
        )
        self._cleanup_thread.start()

        self._balance_thread = threading.Thread(
            target=self._balance_monitor_loop,
            name="UserRecovery-BalanceMonitor",
            daemon=True,
        )
        self._balance_thread.start()

    def stop_recovery(self) -> None:
        """Signal background threads to stop gracefully."""
        logger.info("🛑 UserRecoveryManager: stopping recovery threads...")
        self._stop_event.set()

    def get_status(self) -> Dict[str, Any]:
        """Return a snapshot of the current recovery status."""
        with self._status_lock:
            return dict(self._status)

    # ------------------------------------------------------------------
    # Background threads
    # ------------------------------------------------------------------

    def _cleanup_loop(self) -> None:
        """
        Background thread: run ForcedPositionCleanup for all user accounts
        every CLEANUP_INTERVAL_SECONDS until stopped.

        cancel_open_orders=True ensures pending orders are cancelled on each
        sweep (satisfies Step 3 of the recovery sequence).
        """
        from bot.forced_position_cleanup import ForcedPositionCleanup

        # Close ALL positions: set dust_threshold to $0 so every position
        # qualifies as "dust" and max_positions=0 so every position
        # exceeds the cap.  This is the most reliable way to close everything
        # without adding a new code path.
        cleanup_engine = ForcedPositionCleanup(
            dust_threshold_usd=0.0,
            max_positions=0,
            dry_run=False,
            cancel_open_orders=True,
        )

        logger.info("🧹 UserRecovery: cleanup thread started")

        while not self._stop_event.is_set():
            try:
                self._run_single_cleanup(cleanup_engine)
            except Exception as exc:
                logger.error(f"❌ UserRecovery cleanup sweep failed: {exc}")

            # Wait for next sweep, but allow early wakeup on stop
            self._stop_event.wait(CLEANUP_INTERVAL_SECONDS)

        logger.info("🛑 UserRecovery: cleanup thread stopped")

    def _run_single_cleanup(self, cleanup_engine) -> None:
        """Execute one cleanup sweep across all user accounts."""
        logger.info("🧹 UserRecovery: starting cleanup sweep for all user accounts...")

        # Use the public cleanup_all_accounts API so we don't rely on private internals.
        summary = cleanup_engine.cleanup_all_accounts(
            self.multi_account_manager,
            is_startup=False,
        )

        # summary keys: accounts_processed, total_initial, total_dust, total_cap, total_final, …
        # Update per-user status using aggregate data (individual breakdown not available
        # from the public API, so we record totals under a synthetic '_all' key).
        total_closed = summary.get('total_dust', 0) + summary.get('total_cap', 0)
        total_remaining = summary.get('total_final', 0)

        with self._status_lock:
            self._status['users'].setdefault('_all', {
                'total_closed': 0,
                'remaining_positions': None,
                'last_sweep': None,
            })
            self._status['users']['_all']['total_closed'] += total_closed
            self._status['users']['_all']['remaining_positions'] = total_remaining
            self._status['users']['_all']['last_sweep'] = datetime.now(timezone.utc).isoformat()
            self._status['cleanup_cycles'] += 1
            self._status['last_cleanup_at'] = datetime.now(timezone.utc).isoformat()

        if total_remaining == 0:
            logger.info("✅ UserRecovery: all user positions closed — recovery complete")
        else:
            logger.info(f"   {total_remaining} position(s) still open — next sweep in {CLEANUP_INTERVAL_SECONDS}s")

    def _balance_monitor_loop(self) -> None:
        """
        Background thread: poll each user's balance every
        BALANCE_POLL_INTERVAL_SECONDS and log results.
        """
        logger.info("💰 UserRecovery: balance monitor thread started")

        while not self._stop_event.is_set():
            self._check_user_balances()
            self._stop_event.wait(BALANCE_POLL_INTERVAL_SECONDS)

        logger.info("🛑 UserRecovery: balance monitor thread stopped")

    def _check_user_balances(self) -> None:
        """Fetch and log each user's available balance."""
        logger.info("💰 UserRecovery: balance verification sweep")
        logger.info("-" * 50)

        all_liquid = True

        for user_id, user_broker_dict in self.multi_account_manager.user_brokers.items():
            for broker_type, broker in user_broker_dict.items():
                if not broker or not broker.connected:
                    logger.warning(f"   ⚠️  {user_id}/{broker_type.value}: broker not connected")
                    continue
                try:
                    balance = broker.get_account_balance()
                    positions = broker.get_positions() or []
                    open_position_count = len([p for p in positions if p.get('quantity', 0) > 0])

                    if open_position_count > 0:
                        all_liquid = False
                        logger.info(
                            f"   ⏳ {user_id}/{broker_type.value}: "
                            f"${balance:,.2f} available | {open_position_count} position(s) still open"
                        )
                    else:
                        logger.info(
                            f"   ✅ {user_id}/{broker_type.value}: "
                            f"${balance:,.2f} fully available (0 open positions)"
                        )

                    with self._status_lock:
                        user_entry = self._status['users'].setdefault(user_id, {})
                        user_entry['balance'] = balance
                        user_entry['open_positions'] = open_position_count
                        user_entry['balance_checked_at'] = datetime.now(timezone.utc).isoformat()

                except Exception as exc:
                    logger.error(f"   ❌ {user_id}/{broker_type.value}: balance check failed: {exc}")

        if all_liquid:
            logger.info("✅ UserRecovery: ALL users fully liquid — 100% capital available")
        logger.info("-" * 50)
