"""
NIJA Independent Broker Trader
================================

This module implements FULLY INDEPENDENT trading for each connected brokerage.
Each broker operates in COMPLETE ISOLATION so that one broker NEVER affects another.

CRITICAL ARCHITECTURE PRINCIPLES (Updated Jan 12, 2026):
---------------------------------------------------------
1. PLATFORM ACCOUNT IS COMPLETELY INDEPENDENT OF USER ACCOUNTS
   - Platform (NIJA system) controls itself
   - Users don't affect Master's decisions
   - Master balance != User balances

2. NO BROKER CONTROLS OR AFFECTS OTHER BROKERS
   - Each broker makes its own trading decisions
   - Each broker has its own balance checks
   - Each broker manages its own positions

3. USER ACCOUNTS ARE COMPLETELY INDEPENDENT
   - Each user trades independently on their own brokerage
   - User #1 doesn't affect User #2
   - Users don't affect Platform account

4. FAILURES ARE ISOLATED
   - If Master fails, users keep trading
   - If User #1 fails, Master and other users keep trading
   - If one broker has errors, others continue normally

Key Features:
- Each broker runs in its own thread with error isolation
- Independent health monitoring per broker
- Automatic detection of funded brokers
- Graceful degradation on broker failures
- Separate position tracking per broker

Previously, Coinbase was automatically set as "primary" which caused it to
control trading decisions for ALL brokers. This has been fixed.

Now each broker:
- Makes its own trading decisions
- Has its own balance checks
- Manages its own positions
- Fails independently without affecting others
- Operates on its own schedule (with staggered starts to prevent API rate limits)

Example:
- If Coinbase has an error, Kraken/OKX/Binance continue trading normally
- If Kraken loses connection, it doesn't affect Coinbase/OKX/Binance
- Each broker can have different balances and position limits
- One broker's rate limits don't cascade to others
- Platform account trades independently from all user accounts
"""

import os
import sys
import time
import logging
import random
import threading
from typing import Dict, List, Optional, Set
from datetime import datetime

# Import BrokerType for connection order enforcement
try:
    from bot.broker_manager import BrokerType
except ImportError:
    from broker_manager import BrokerType

# Import copy trade engine for checking if copy trading is active
try:
    from bot.copy_trade_engine import get_copy_engine
except ImportError:
    # Handle case where bot module path isn't available
    try:
        from copy_trade_engine import get_copy_engine
    except ImportError:
        # If we can't import, we'll handle it gracefully in the code
        get_copy_engine = None

logger = logging.getLogger("nija.independent_trader")

# Minimum balance required for active trading
MINIMUM_FUNDED_BALANCE = 0.50  # Lowered from 1.0 to allow trading with very small balances (e.g., $0.76)

# Startup delay constants (Jan 10, 2026) - Prevent API rate limiting during initialization
STARTUP_DELAY_MIN = 30.0  # Minimum delay before first trading cycle (seconds)
STARTUP_DELAY_MAX = 60.0  # Maximum delay before first trading cycle (seconds)
BROKER_STAGGER_DELAY = 10.0  # Delay between starting each broker thread (seconds)


class IndependentBrokerTrader:
    """
    Manages independent trading operations across multiple brokers.
    Each broker operates in isolation to prevent cascade failures.
    """

    def __init__(self, broker_manager, trading_strategy, multi_account_manager=None):
        """
        Initialize independent broker trader.

        Args:
            broker_manager: BrokerManager instance with connected brokers
            trading_strategy: TradingStrategy instance for trading logic
            multi_account_manager: Optional MultiAccountBrokerManager for user accounts
        """
        self.broker_manager = broker_manager
        self.trading_strategy = trading_strategy
        self.multi_account_manager = multi_account_manager

        # Track broker health and status
        self.broker_health: Dict[str, Dict] = {}
        self.broker_threads: Dict[str, threading.Thread] = {}
        self.stop_flags: Dict[str, threading.Event] = {}
        self.funded_brokers: Set[str] = set()

        # Track user account brokers separately
        self.user_broker_health: Dict[str, Dict[str, Dict]] = {}  # {user_id: {broker_name: health_dict}}
        self.user_broker_threads: Dict[str, Dict[str, threading.Thread]] = {}  # {user_id: {broker_name: thread}}
        self.user_stop_flags: Dict[str, Dict[str, threading.Event]] = {}  # {user_id: {broker_name: event}}

        # Thread safety locks
        self.health_lock = threading.Lock()

        # FIX #2 (Jan 19, 2026): Thread singleton guard
        # Prevents duplicate trading threads for same broker
        # Structure: set of broker names currently running threads
        self.active_trading_threads: Set[str] = set()
        self.active_threads_lock = threading.Lock()

        logger.info("=" * 70)
        logger.info("🔒 INDEPENDENT BROKER TRADER INITIALIZED")
        if multi_account_manager:
            logger.info("   ✅ Multi-account support enabled (user trading)")
        logger.info("=" * 70)

    def _get_platform_broker_source(self):
        """
        Get the authoritative source for master brokers.

        Returns the multi_account_manager.platform_brokers if available,
        otherwise falls back to the legacy broker_manager.brokers.

        Returns:
            dict: Dictionary of BrokerType -> BaseBroker instances
        """
        return self.multi_account_manager.platform_brokers if self.multi_account_manager else self.broker_manager.brokers

    def _retry_coinbase_balance_if_zero(self, broker, broker_name: str) -> float:
        """
        Retry balance fetch for Coinbase if initial result is $0.

        Coinbase API can return stale/cached $0 balance immediately after connection
        due to API-side caching. This method retries with increasing delays and
        cache clearing to get fresh balance data.

        Args:
            broker: Broker instance (must be Coinbase)
            broker_name: Human-readable broker name for logging

        Returns:
            float: Balance after retries, or 0.0 if still zero after all attempts
        """
        balance = broker.get_account_balance()

        if balance > 0:
            return balance  # No need to retry if we got a balance

        # Balance is $0, start retry logic
        logger.warning(f"   {broker_name} returned $0.00, retrying with delays to bypass API cache...")

        for attempt in range(3):  # Try 3 times
            retry_num = attempt + 1
            delay = retry_num * 2.0  # 2s, 4s, 6s
            logger.debug(f"   Retry #{retry_num}/3: waiting {delay:.0f}s before retry...")
            time.sleep(delay)

            # Clear cache to force fresh API calls
            if hasattr(broker, 'clear_cache'):
                broker.clear_cache()
            else:
                # Fallback for brokers without clear_cache method
                if hasattr(broker, '_balance_cache'):
                    broker._balance_cache = None
                    broker._balance_cache_time = None
                if hasattr(broker, '_accounts_cache'):
                    broker._accounts_cache = None
                    broker._accounts_cache_time = None
            logger.debug(f"   Cache cleared, fetching fresh balance...")

            balance = broker.get_account_balance()
            logger.debug(f"   Retry #{retry_num}/3 returned: ${balance:.2f}")

            if balance > 0:
                logger.info(f"   ✅ Balance detected after retry #{retry_num}/3")
                return balance

        # All retries exhausted, still $0
        logger.warning(f"   ⚠️  All 3 retries exhausted, balance still $0.00")
        logger.warning(f"   This likely means:")
        logger.warning(f"      1. No funds in Advanced Trade portfolio")
        logger.warning(f"      2. Funds may be in Consumer wallet (not API-accessible)")
        logger.warning(f"      3. Transfer funds: https://www.coinbase.com/advanced-portfolio")

        return 0.0

    def detect_funded_brokers(self) -> Dict[str, float]:
        """
        Detect which brokers are funded and ready to trade.

        Returns:
            dict: Mapping of broker type name to balance for funded brokers
        """
        funded = {}

        logger.info("=" * 70)
        logger.info("🔍 DETECTING FUNDED PLATFORM BROKERS")
        logger.info("=" * 70)

        # CRITICAL FIX (Jan 16, 2026): Use multi_account_manager.platform_brokers instead of broker_manager.brokers
        # The old broker_manager is kept for backward compatibility, but master brokers are now
        # managed through multi_account_manager for consistency with user broker management
        broker_source = self._get_platform_broker_source()

        logger.info(f"📋 Total PLATFORM brokers configured: {len(broker_source)}")
        for broker_type, broker in broker_source.items():
            logger.info(f"   • {broker_type.value.upper()}: {'connected' if broker.connected else 'not connected'}")
        logger.info("")

        for broker_type, broker in broker_source.items():
            broker_name_upper = broker_type.value.upper()

            logger.info(f"🔍 Checking {broker_name_upper} PLATFORM...")

            if not broker.connected:
                logger.warning(f"   ⚪ {broker_name_upper}: Not connected during initialization")
                logger.info(f"   🔄 Attempting balance check (may reconnect)...")
                # Don't 'continue' here - fall through to try balance fetch

            try:
                # Fetch balance, with retry logic for Coinbase if needed
                if broker_type.value == 'coinbase':
                    balance = self._retry_coinbase_balance_if_zero(broker, broker_name_upper)
                else:
                    balance = broker.get_account_balance()

                logger.info(f"   💰 {broker_name_upper} Balance: ${balance:,.2f}")

                # Check if broker has minimum funding
                if balance >= MINIMUM_FUNDED_BALANCE:
                    funded[broker_type.value] = balance
                    self.funded_brokers.add(broker_type.value)
                    logger.info(f"   ✅ {broker_name_upper} FUNDED - Ready to trade")
                    logger.info(f"   📊 {broker_name_upper} will start independent trading thread")
                else:
                    logger.warning(f"   ⚠️  {broker_name_upper} UNDERFUNDED")
                    logger.warning(f"      Current: ${balance:,.2f}")
                    logger.warning(f"      Minimum: ${MINIMUM_FUNDED_BALANCE:.2f}")
                    logger.warning(f"   ❌ {broker_name_upper} will NOT trade (add funds to enable)")

            except Exception as e:
                logger.error(f"   ❌ {broker_name_upper} ERROR checking balance: {e}")
                logger.warning(f"   ⚠️  {broker_name_upper} will NOT trade (balance check failed)")

            logger.info("")  # Blank line between brokers

        logger.info("=" * 70)
        if funded:
            logger.info(f"✅ FUNDED PLATFORM BROKERS: {len(funded)}")
            total_capital = sum(funded.values())
            logger.info(f"💰 TOTAL PLATFORM TRADING CAPITAL: ${total_capital:,.2f}")
            logger.info("")
            logger.info("📊 Breakdown:")
            for broker_name, balance in funded.items():
                logger.info(f"   • {broker_name.upper()}: ${balance:,.2f}")
        else:
            logger.error("❌ NO FUNDED PLATFORM BROKERS DETECTED")
            logger.error("   No PLATFORM brokers have sufficient balance to trade")
            logger.error("   PLATFORM trading loops will NOT start")
        logger.info("=" * 70)
        logger.info("")

        return funded

    def detect_funded_user_brokers(self) -> Dict[str, Dict[str, float]]:
        """
        Detect which user brokers are funded and ready to trade.

        Returns:
            dict: Nested dict {user_id: {broker_name: balance}} for funded user brokers
        """
        if not self.multi_account_manager:
            return {}

        funded_users = {}

        logger.info("🔍 Detecting funded user brokers...")

        # Check all user accounts
        for user_id, user_brokers in self.multi_account_manager.user_brokers.items():
            for broker_type, broker in user_brokers.items():
                broker_name = f"{user_id}_{broker_type.value}"

                if not broker.connected:
                    logger.info(f"   ⚪ User: {user_id} | {broker_type.value}: Not connected initially")
                    # Give disconnected brokers a chance to reconnect by attempting balance check (self-healing)
                    logger.info(f"   🔄 Attempting balance check for User: {user_id} | {broker_type.value} (may reconnect)...")
                    # Don't 'continue' here - fall through to try balance fetch

                try:
                    # Fetch balance, with retry logic for Coinbase if needed
                    if broker_type.value == 'coinbase':
                        balance = self._retry_coinbase_balance_if_zero(broker, f"User {user_id} Coinbase")
                    else:
                        balance = broker.get_account_balance()

                    logger.info(f"   💰 User: {user_id} | {broker_type.value}: ${balance:,.2f}")

                    if balance >= MINIMUM_FUNDED_BALANCE:
                        if user_id not in funded_users:
                            funded_users[user_id] = {}
                        funded_users[user_id][broker_type.value] = balance
                        logger.info(f"      ✅ FUNDED - Ready to trade")
                    else:
                        logger.info(f"      ⚠️  Underfunded (minimum: ${MINIMUM_FUNDED_BALANCE:.2f})")

                except Exception as e:
                    logger.warning(f"   ❌ User: {user_id} | {broker_type.value}: Error checking balance: {e}")

        logger.info("=" * 70)
        if funded_users:
            total_user_count = len(funded_users)
            total_broker_count = sum(len(brokers) for brokers in funded_users.values())
            total_user_capital = sum(sum(brokers.values()) for brokers in funded_users.values())

            logger.info(f"✅ FUNDED USER ACCOUNTS: {total_user_count}")
            logger.info(f"✅ FUNDED USER BROKERS: {total_broker_count}")
            logger.info(f"💰 TOTAL USER TRADING CAPITAL: ${total_user_capital:,.2f}")

            for user_id, brokers in funded_users.items():
                user_total = sum(brokers.values())
                logger.info(f"   👤 {user_id}: ${user_total:,.2f}")
                for broker_name, balance in brokers.items():
                    logger.info(f"      • {broker_name}: ${balance:,.2f}")
        else:
            # Check if copy trading engine is active
            if get_copy_engine is not None:
                try:
                    copy_trading_engine = get_copy_engine()
                    if copy_trading_engine.active:
                        logger.info("ℹ️  No independent USER brokers detected (users operate via copy trading)")
                    else:
                        logger.warning("⚠️  No funded USER brokers detected")
                except Exception:
                    # If we can't check the copy engine, fall back to warning
                    logger.warning("⚠️  No funded USER brokers detected")
            else:
                # If get_copy_engine wasn't imported, fall back to warning
                logger.warning("⚠️  No funded USER brokers detected")
        logger.info("=" * 70)

        return funded_users

    def get_broker_health_status(self, broker_name: str) -> Dict:
        """
        Get health status for a specific broker.

        Args:
            broker_name: Name of the broker

        Returns:
            dict: Health status information
        """
        with self.health_lock:
            return self.broker_health.get(broker_name, {
                'status': 'unknown',
                'last_check': None,
                'error_count': 0,
                'last_error': None,
                'is_trading': False
            })

    def update_broker_health(self, broker_name: str, status: str,
                            error: Optional[str] = None,
                            is_trading: bool = False):
        """
        Update health status for a broker.

        Args:
            broker_name: Name of the broker
            status: Health status ('healthy', 'degraded', 'failed')
            error: Optional error message
            is_trading: Whether broker is actively trading
        """
        with self.health_lock:
            if broker_name not in self.broker_health:
                self.broker_health[broker_name] = {
                    'status': status,
                    'last_check': datetime.now(),
                    'error_count': 0,
                    'last_error': None,
                    'is_trading': is_trading,
                    'total_cycles': 0,
                    'successful_cycles': 0
                }

            current = self.broker_health[broker_name]
            current['status'] = status
            current['last_check'] = datetime.now()
            current['is_trading'] = is_trading
            current['total_cycles'] = current.get('total_cycles', 0) + 1

            if error:
                current['error_count'] = current.get('error_count', 0) + 1
                current['last_error'] = error
                logger.warning(f"⚠️  {broker_name} health degraded: {error}")
            else:
                current['successful_cycles'] = current.get('successful_cycles', 0) + 1
                # Reset error count on success
                if current.get('error_count', 0) > 0:
                    logger.info(f"✅ {broker_name} recovered from errors")
                current['error_count'] = 0
                current['last_error'] = None

    def _display_capital_scaling_banner(self):
        """
        Display the NIJA Capital Scaling Protocol startup banner.
        This banner is shown once when a trading loop starts.
        """
        logger.info("")
        logger.info("   " + "=" * 70)
        logger.info("   🔥 NIJA Capital Scaling Protocol 🔥")
        logger.info("   " + "=" * 70)
        logger.info("   📈 Mathematically optimal compounding roadmap")
        logger.info("   💰 Automatic profit reinvestment for exponential growth")
        logger.info("   🛡️  Drawdown protection and capital preservation")
        logger.info("   🎯 Milestone tracking and progressive scaling")
        logger.info("   " + "=" * 70)
        logger.info("")

    def run_broker_trading_loop(self, broker_type, broker, stop_flag: threading.Event):
        """
        Run independent trading loop for a single broker.
        This runs in a separate thread with full error isolation.

        Args:
            broker_type: BrokerType enum
            broker: BaseBroker instance
            stop_flag: Threading event to signal stop
        """
        broker_name = broker_type.value
        cycle_count = 0

        logger.info(f"🚀 Starting independent trading loop for {broker_name}")

        # CRITICAL FIX (Jan 10, 2026): Add startup delay to prevent concurrent API calls
        # During bot initialization, multiple operations happen simultaneously:
        # - Portfolio detection, position checking, balance fetching all hit the API at once
        # This causes rate limiting before trading even begins
        # Wait 30-60 seconds before starting trading loop to let initialization settle
        startup_delay = STARTUP_DELAY_MIN + random.uniform(0, STARTUP_DELAY_MAX - STARTUP_DELAY_MIN)
        logger.info(f"   ⏳ {broker_name}: Waiting {startup_delay:.1f}s before first cycle (prevents rate limiting)...")
        stop_flag.wait(startup_delay)

        if stop_flag.is_set():
            logger.info(f"🛑 {broker_name} stopped before first cycle")
            return

        # Display Capital Scaling Protocol banner (once at startup)
        self._display_capital_scaling_banner()

        while not stop_flag.is_set():
            cycle_count += 1

            try:
                logger.info(f"🔄 {broker_name} - Cycle #{cycle_count}")

                # Check if broker is still funded
                try:
                    balance = broker.get_account_balance()
                    if balance < MINIMUM_FUNDED_BALANCE:
                        logger.warning(f"⚠️  {broker_name} balance too low: ${balance:.2f}")
                        self.update_broker_health(broker_name, 'degraded',
                                                 f'Underfunded: ${balance:.2f}')
                        # Wait before rechecking
                        stop_flag.wait(60)
                        continue
                except Exception as balance_err:
                    logger.error(f"❌ {broker_name} balance check failed: {balance_err}")
                    self.update_broker_health(broker_name, 'degraded',
                                             f'Balance check failed: {str(balance_err)[:50]}')
                    # Wait before retry
                    stop_flag.wait(30)
                    continue

                # Run trading cycle for this broker
                try:
                    # CRITICAL FIX (Jan 11, 2026): Pass broker to run_cycle() instead of setting shared state
                    # Previously, we set self.trading_strategy.broker = broker which caused race conditions
                    # when multiple threads tried to set this shared variable simultaneously.
                    # Now we pass the broker as a parameter, making each thread truly independent.

                    # ENHANCED LOGGING (Jan 18, 2026): Show exactly what's about to happen
                    logger.info(f"   ═══════════════════════════════════════════════════════════")
                    logger.info(f"   🎯 {broker_name.upper()} PLATFORM TRADING CYCLE #{cycle_count}")
                    logger.info(f"   ═══════════════════════════════════════════════════════════")
                    logger.info(f"   💰 Current balance: ${balance:.2f}")
                    logger.info(f"   📊 Mode: PLATFORM (full strategy execution)")
                    logger.info(f"   🔍 Will scan markets for opportunities")
                    logger.info(f"   ⚡ Will execute trades if signals trigger")
                    logger.info(f"   🔄 Will manage existing positions")
                    logger.info(f"   ═══════════════════════════════════════════════════════════")

                    # Execute trading cycle for THIS broker only (thread-safe)
                    self.trading_strategy.run_cycle(broker=broker)

                    # Mark as healthy
                    self.update_broker_health(broker_name, 'healthy', is_trading=True)
                    logger.info(f"   ✅ {broker_name.upper()} cycle completed successfully")
                    logger.info("")

                except Exception as trading_err:
                    logger.error(f"❌ {broker_name} trading cycle failed: {trading_err}")
                    logger.error(f"   Error type: {type(trading_err).__name__}")

                    # Update health status
                    self.update_broker_health(broker_name, 'degraded',
                                             f'Trading error: {str(trading_err)[:100]}')

                    # Continue to next cycle - don't let one broker's failure stop everything
                    logger.info(f"   ⚠️  {broker_name} will retry next cycle")

                # Wait 150 seconds (2.5 minutes) between cycles
                # Use stop_flag.wait() so we can be interrupted for shutdown
                logger.info(f"   {broker_name}: Waiting 2.5 minutes until next cycle...")
                stop_flag.wait(150)

            except Exception as outer_err:
                # Catch-all for any unexpected errors
                logger.error(f"❌ {broker_name} CRITICAL ERROR in trading loop: {outer_err}")
                self.update_broker_health(broker_name, 'failed',
                                         f'Critical error: {str(outer_err)[:100]}')

                # Wait before retry
                stop_flag.wait(60)

        # Cleanup: Remove from active threads when loop exits
        with self.active_threads_lock:
            self.active_trading_threads.discard(broker_name)

        logger.info(f"🛑 {broker_name} trading loop stopped (total cycles: {cycle_count})")
        logger.info(f"   Thread removed from active trading threads")

    def run_user_broker_trading_loop(self, user_id: str, broker_type, broker, stop_flag: threading.Event):
        """
        Run trading loop for a USER broker in an isolated thread.
        Each user broker operates completely independently from master brokers and other users.

        Args:
            user_id: User identifier (e.g., 'daivon_frazier')
            broker_type: Broker type enum
            broker: Broker instance
            stop_flag: Threading event to signal shutdown
        """
        broker_name = f"{user_id}_{broker_type.value}"
        logger.info(f"🚀 {broker_name} (USER) trading loop started")

        # Random startup delay to prevent all user brokers hitting API at once
        startup_delay = random.uniform(STARTUP_DELAY_MIN, STARTUP_DELAY_MAX)
        logger.info(f"   ⏳ {broker_name}: Initial startup delay {startup_delay:.1f}s...")
        stop_flag.wait(startup_delay)

        if stop_flag.is_set():
            logger.info(f"🛑 {broker_name} stopped before first cycle")
            return

        # Display Capital Scaling Protocol banner (once at startup)
        self._display_capital_scaling_banner()

        cycle_count = 0

        while not stop_flag.is_set():
            try:
                cycle_count += 1
                logger.info(f"🔄 {broker_name} (USER) - Cycle #{cycle_count}")

                # Check if broker is still funded
                try:
                    balance = broker.get_account_balance()
                    if balance < MINIMUM_FUNDED_BALANCE:
                        logger.warning(f"⚠️  {broker_name} (USER) balance too low: ${balance:.2f}")
                        # Store health in user-specific tracking
                        if user_id not in self.user_broker_health:
                            self.user_broker_health[user_id] = {}
                        self.user_broker_health[user_id][broker_name] = {
                            'status': 'degraded',
                            'error': f'Underfunded: ${balance:.2f}',
                            'last_check': datetime.now()
                        }
                        # Wait before rechecking
                        stop_flag.wait(60)
                        continue
                except Exception as balance_err:
                    logger.error(f"❌ {broker_name} (USER) balance check failed: {balance_err}")
                    if user_id not in self.user_broker_health:
                        self.user_broker_health[user_id] = {}
                    self.user_broker_health[user_id][broker_name] = {
                        'status': 'degraded',
                        'error': f'Balance check failed: {str(balance_err)[:50]}',
                        'last_check': datetime.now()
                    }
                    # Wait before retry
                    stop_flag.wait(30)
                    continue

                # Run trading cycle for this user broker
                try:
                    # USER accounts should NEVER generate signals
                    # Users only execute copy trades from master - they don't run strategy themselves
                    # This prevents users from making independent trading decisions
                    # Copy trading is handled by the CopyTradeEngine which listens for master signals

                    # Execute trading cycle for THIS user broker only (thread-safe)
                    # USER accounts ONLY do position management (exits), NOT entry signals
                    logger.info(f"   {broker_name} (USER): Running position management (NO signal generation)...")
                    self.trading_strategy.run_cycle(broker=broker, user_mode=True)

                    # Mark as healthy
                    if user_id not in self.user_broker_health:
                        self.user_broker_health[user_id] = {}
                    self.user_broker_health[user_id][broker_name] = {
                        'status': 'healthy',
                        'error': None,
                        'last_check': datetime.now(),
                        'is_trading': True,
                        'total_cycles': self.user_broker_health.get(user_id, {}).get(broker_name, {}).get('total_cycles', 0) + 1
                    }
                    logger.info(f"   ✅ {broker_name} (USER) cycle completed successfully")

                except Exception as trading_err:
                    logger.error(f"❌ {broker_name} (USER) trading cycle failed: {trading_err}")
                    logger.error(f"   Error type: {type(trading_err).__name__}")

                    # Update health status
                    if user_id not in self.user_broker_health:
                        self.user_broker_health[user_id] = {}
                    self.user_broker_health[user_id][broker_name] = {
                        'status': 'degraded',
                        'error': f'Trading error: {str(trading_err)[:100]}',
                        'last_check': datetime.now()
                    }

                    # Continue to next cycle - don't let one user broker's failure stop everything
                    logger.info(f"   ⚠️  {broker_name} (USER) will retry next cycle")

                # Wait 150 seconds (2.5 minutes) between cycles
                # Use stop_flag.wait() so we can be interrupted for shutdown
                logger.info(f"   {broker_name} (USER): Waiting 2.5 minutes until next cycle...")
                stop_flag.wait(150)

            except Exception as outer_err:
                # Catch-all for any unexpected errors
                logger.error(f"❌ {broker_name} (USER) CRITICAL ERROR in trading loop: {outer_err}")
                if user_id not in self.user_broker_health:
                    self.user_broker_health[user_id] = {}
                self.user_broker_health[user_id][broker_name] = {
                    'status': 'failed',
                    'error': f'Critical error: {str(outer_err)[:100]}',
                    'last_check': datetime.now()
                }

                # Wait before retry
                stop_flag.wait(60)

        logger.info(f"🛑 {broker_name} (USER) trading loop stopped (total cycles: {cycle_count})")

    def start_independent_trading(self):
        """
        Start independent trading threads for all funded brokers.
        Each broker operates completely independently.
        Includes both PLATFORM brokers and USER brokers.

        Returns:
            bool: True if at least one trading thread was started, False otherwise
        """
        logger.info("=" * 70)
        logger.info("🚀 STARTING INDEPENDENT MULTI-BROKER TRADING")
        logger.info("=" * 70)

        # Detect funded PLATFORM brokers
        funded = self.detect_funded_brokers()

        # Detect funded USER brokers
        funded_users = self.detect_funded_user_brokers()

        if not funded and not funded_users:
            logger.error("❌ No funded brokers detected (master or user). Cannot start trading.")
            return False

        total_threads = 0

        # Start threads for PLATFORM brokers
        if funded:
            logger.info("")
            logger.info("=" * 70)
            logger.info("🔷 STARTING PLATFORM BROKER TRADING THREADS")
            logger.info("=" * 70)
            logger.info(f"📊 {len(funded)} PLATFORM broker(s) ready to trade")
            logger.info("")

            # CRITICAL FIX (Jan 16, 2026): Use multi_account_manager.platform_brokers instead of broker_manager.brokers
            # This ensures we iterate over the same broker instances that were checked in detect_funded_brokers()
            broker_source = self._get_platform_broker_source()

            broker_start_count = 0
            for broker_type, broker in broker_source.items():
                broker_name = broker_type.value
                broker_name_upper = broker_name.upper()

                logger.info(f"🔍 Processing {broker_name_upper} PLATFORM...")

                # Only start threads for funded brokers
                if broker_name not in funded:
                    logger.info(f"   ⏭️  SKIPPING - Not funded (balance < ${MINIMUM_FUNDED_BALANCE:.2f})")
                    logger.info("")
                    continue

                if not broker.connected:
                    logger.warning(f"   ⚠️  SKIPPING - Not connected")
                    logger.warning(f"   📋 Reason: Connection failed during initialization")
                    logger.info("")
                    continue

                logger.info(f"   ✅ {broker_name_upper} is funded and connected")
                logger.info(f"   💰 Balance: ${funded[broker_name]:,.2f}")

                # FIX #2 (Jan 19, 2026): Thread singleton guard
                # Check if trading thread already running for this broker
                with self.active_threads_lock:
                    if broker_name in self.active_trading_threads:
                        logger.warning(f"   ⚠️  Trading thread already running for {broker_name_upper} — skipping")
                        logger.warning(f"   This prevents duplicate trading loops and double orders")
                        logger.info("")
                        continue

                # CRITICAL FIX (Jan 10, 2026): Stagger broker thread starts to prevent concurrent API bursts
                # If we start all brokers simultaneously, they all hit the API at once causing rate limits
                # Add a delay between each broker start (except the first one)
                if broker_start_count > 0:
                    logger.info(f"   ⏳ Staggering start: waiting {BROKER_STAGGER_DELAY:.0f}s before starting thread...")
                    time.sleep(BROKER_STAGGER_DELAY)

                # Create stop flag for this broker
                stop_flag = threading.Event()
                self.stop_flags[broker_name] = stop_flag

                # Register this broker as having an active thread
                with self.active_threads_lock:
                    self.active_trading_threads.add(broker_name)

                # Create and start trading thread
                thread = threading.Thread(
                    target=self.run_broker_trading_loop,
                    args=(broker_type, broker, stop_flag),
                    name=f"Trader-{broker_name}",
                    daemon=True
                )

                self.broker_threads[broker_name] = thread
                thread.start()
                broker_start_count += 1
                total_threads += 1

                logger.info(f"   🚀 TRADING THREAD STARTED for {broker_name_upper} (PLATFORM)")
                logger.info(f"   📊 Thread name: Trader-{broker_name}")
                logger.info(f"   🔄 This thread will:")
                logger.info(f"      • Scan markets every 2.5 minutes")
                logger.info(f"      • Execute PLATFORM trades when signals trigger")
                logger.info(f"      • Manage existing positions")
                logger.info("")
        else:
            logger.warning("=" * 70)
            logger.warning("⚠️  NO PLATFORM BROKER THREADS TO START")
            logger.warning("=" * 70)
            logger.warning("Reason: No funded PLATFORM brokers detected")
            logger.warning("PLATFORM trading will NOT occur until brokers are funded")
            logger.warning("=" * 70)
            logger.warning("")

        # Start threads for USER brokers
        if funded_users:
            logger.info("=" * 70)
            logger.info("👤 STARTING USER BROKER THREADS")
            logger.info("=" * 70)

            user_broker_start_count = 0
            for user_id, user_brokers in self.multi_account_manager.user_brokers.items():
                for broker_type, broker in user_brokers.items():
                    broker_name = f"{user_id}_{broker_type.value}"

                    # CRITICAL FIX (Jan 17, 2026): Disable independent strategy loops for Kraken USER accounts
                    # When copy trading is active, Kraken users should ONLY execute copied trades from master
                    # They should NOT run their own independent strategy loops (prevents conflicting signals)
                    if broker_type == BrokerType.KRAKEN:
                        # Check if Kraken master is connected (indicates copy trading is active)
                        kraken_platform_connected = self.multi_account_manager.is_platform_connected(BrokerType.KRAKEN)
                        if kraken_platform_connected:
                            logger.info(f"⏭️  Skipping {broker_name} - Kraken copy trading active (users receive copied trades only)")
                            logger.info(f"   ℹ️  {user_id} will execute trades copied from Kraken PLATFORM")
                            logger.info(f"   ℹ️  Independent strategy loop disabled for copy trading mode")
                            continue
                        else:
                            logger.info(f"⏭️  Skipping {broker_name} - Kraken PLATFORM offline")
                            logger.info(f"   ℹ️  Kraken copy trading disabled until MASTER reconnects")
                            logger.info(f"   ✅ OTHER BROKERS (Coinbase, etc.) continue trading independently")
                            continue

                    # Only start threads for funded user brokers
                    if user_id not in funded_users or broker_type.value not in funded_users[user_id]:
                        logger.info(f"⏭️  Skipping {broker_name} (not funded)")
                        continue

                    if not broker.connected:
                        logger.warning(f"⏭️  Skipping {broker_name} (not connected)")
                        continue

                    # Stagger user broker thread starts
                    if user_broker_start_count > 0 or total_threads > 0:
                        logger.info(f"   ⏳ Staggering start: waiting {BROKER_STAGGER_DELAY:.0f}s before starting {broker_name}...")
                        time.sleep(BROKER_STAGGER_DELAY)

                    # Initialize user broker tracking dictionaries if needed
                    if user_id not in self.user_stop_flags:
                        self.user_stop_flags[user_id] = {}
                    if user_id not in self.user_broker_threads:
                        self.user_broker_threads[user_id] = {}
                    if user_id not in self.user_broker_health:
                        self.user_broker_health[user_id] = {}

                    # Create stop flag for this user broker
                    stop_flag = threading.Event()
                    self.user_stop_flags[user_id][broker_name] = stop_flag

                    # Create and start trading thread
                    thread = threading.Thread(
                        target=self.run_user_broker_trading_loop,
                        args=(user_id, broker_type, broker, stop_flag),
                        name=f"Trader-{broker_name}",
                        daemon=True
                    )

                    self.user_broker_threads[user_id][broker_name] = thread
                    thread.start()
                    user_broker_start_count += 1
                    total_threads += 1

                    logger.info(f"✅ Started independent trading thread for {broker_name} (USER)")

        logger.info("=" * 70)
        logger.info(f"✅ {total_threads} INDEPENDENT TRADING THREADS RUNNING")
        logger.info("=" * 70)

        # Enhanced summary showing MASTER vs USER breakdown
        platform_count = len(self.broker_threads)
        user_count = sum(len(threads) for threads in self.user_broker_threads.values()) if any(self.user_broker_threads.values()) else 0

        if self.broker_threads:
            broker_names = ", ".join(sorted(self.broker_threads.keys()))
            logger.info(f"🔷 PLATFORM BROKERS ({platform_count} trading thread{'s' if platform_count != 1 else ''}):")
            for broker_name in sorted(self.broker_threads.keys()):
                logger.info(f"   • {broker_name.upper()} MASTER → Will generate trade signals")
        else:
            logger.warning("⚠️  NO PLATFORM BROKER THREADS STARTED")
            logger.warning("   PLATFORM trading will NOT occur")

        if any(self.user_broker_threads.values()):
            total_user_threads = sum(len(threads) for threads in self.user_broker_threads.values())
            logger.info(f"👤 USER BROKERS ({total_user_threads} trading thread{'s' if total_user_threads != 1 else ''}):")
            # Collect all user broker names
            for user_id, threads in self.user_broker_threads.items():
                for broker_name in sorted(threads.keys()):
                    broker_type_name = broker_name.split('_', 1)[1] if '_' in broker_name else broker_name
                    logger.info(f"   • {user_id.upper()} ({broker_type_name.upper()}) → Will receive copied trades")
        else:
            logger.info("   ℹ️  No USER broker threads (copy trading via CopyTradeEngine)")

        logger.info("=" * 70)
        logger.info("")

        # CRITICAL: Show explicit PLATFORM trading status
        logger.info("=" * 70)
        logger.info("🎯 MASTER TRADING STATUS")
        logger.info("=" * 70)
        if platform_count > 0:
            logger.info(f"✅ {platform_count} PLATFORM broker{'s' if platform_count != 1 else ''} WILL TRADE")
            logger.info(f"   Trade signals will be generated every 2.5 minutes")
            logger.info(f"   Users will receive copies via CopyTradeEngine")
        else:
            logger.error("❌ NO PLATFORM BROKERS WILL TRADE")
            logger.error("   No trading signals will be generated")
            logger.error("   User accounts will NOT receive trades (no signals to copy)")
            logger.error("")
            logger.error("   🔧 To fix: Ensure PLATFORM brokers are:")
            logger.error("      1. Connected (credentials valid)")
            logger.error("      2. Funded (balance >= $0.50)")
            logger.error("      3. Not blocked by errors")
        logger.info("=" * 70)
        logger.info("")

        # Return True if at least one thread was started
        return total_threads > 0

    def stop_all_trading(self):
        """
        Stop all trading threads gracefully (both master and user brokers).
        """
        logger.info("🛑 Stopping all independent trading threads...")

        # Signal all PLATFORM broker threads to stop
        for broker_name, stop_flag in self.stop_flags.items():
            logger.info(f"   Signaling {broker_name} (PLATFORM) to stop...")
            stop_flag.set()

        # Signal all USER broker threads to stop
        for user_id, user_stop_flags in self.user_stop_flags.items():
            for broker_name, stop_flag in user_stop_flags.items():
                logger.info(f"   Signaling {broker_name} (USER) to stop...")
                stop_flag.set()

        # Wait for all MASTER threads to finish (with timeout)
        for broker_name, thread in self.broker_threads.items():
            logger.info(f"   Waiting for {broker_name} (PLATFORM) thread to finish...")
            thread.join(timeout=10)
            if thread.is_alive():
                logger.warning(f"   ⚠️  {broker_name} (PLATFORM) thread did not stop gracefully")
            else:
                logger.info(f"   ✅ {broker_name} (PLATFORM) thread stopped")

        # Wait for all USER threads to finish (with timeout)
        for user_id, user_threads in self.user_broker_threads.items():
            for broker_name, thread in user_threads.items():
                logger.info(f"   Waiting for {broker_name} (USER) thread to finish...")
                thread.join(timeout=10)
                if thread.is_alive():
                    logger.warning(f"   ⚠️  {broker_name} (USER) thread did not stop gracefully")
                else:
                    logger.info(f"   ✅ {broker_name} (USER) thread stopped")

        logger.info("✅ All trading threads stopped")

    def get_status_summary(self) -> Dict:
        """
        Get summary of all broker statuses.

        Returns:
            dict: Summary of broker health and trading status
        """
        # CRITICAL FIX (Jan 16, 2026): Use multi_account_manager.platform_brokers for accurate counts
        broker_source = self._get_platform_broker_source()

        summary = {
            'total_brokers': len(broker_source),
            'connected_brokers': sum(1 for b in broker_source.values() if b.connected),
            'funded_brokers': len(self.funded_brokers),
            'trading_threads': len(self.broker_threads),
            'broker_details': {}
        }

        with self.health_lock:
            for broker_name, health in self.broker_health.items():
                summary['broker_details'][broker_name] = {
                    'status': health.get('status', 'unknown'),
                    'is_trading': health.get('is_trading', False),
                    'error_count': health.get('error_count', 0),
                    'total_cycles': health.get('total_cycles', 0),
                    'successful_cycles': health.get('successful_cycles', 0),
                    'success_rate': (
                        health.get('successful_cycles', 0) / health.get('total_cycles', 1) * 100
                        if health.get('total_cycles', 0) > 0 else 0
                    )
                }

        return summary

    def log_status_summary(self):
        """
        Log a summary of all broker trading statuses with active positions.
        """
        summary = self.get_status_summary()

        logger.info("=" * 70)
        logger.info("📊 MULTI-BROKER TRADING STATUS SUMMARY")
        logger.info("=" * 70)
        logger.info(f"Total Brokers: {summary['total_brokers']}")
        logger.info(f"Connected: {summary['connected_brokers']}")
        logger.info(f"Funded: {summary['funded_brokers']}")
        logger.info(f"Active Trading Threads: {summary['trading_threads']}")
        logger.info("")

        for broker_name, details in summary['broker_details'].items():
            logger.info(f"{broker_name}:")
            logger.info(f"   Status: {details['status']}")
            logger.info(f"   Trading: {'✅ Yes' if details['is_trading'] else '❌ No'}")
            logger.info(f"   Cycles: {details['successful_cycles']}/{details['total_cycles']} successful")
            logger.info(f"   Success Rate: {details['success_rate']:.1f}%")
            if details['error_count'] > 0:
                logger.info(f"   ⚠️  Recent Errors: {details['error_count']}")

        logger.info("=" * 70)

        # Log active positions for all funded brokers (master and users)
        self._log_all_active_positions()

    def _log_all_active_positions(self):
        """
        Log active positions for all funded brokers (master and users).
        Shows which brokerages have active trades and position details.
        """
        logger.info("")
        logger.info("=" * 70)
        logger.info("📈 ACTIVE POSITIONS ACROSS ALL FUNDED BROKERS")
        logger.info("=" * 70)

        total_positions = 0
        brokers_with_positions = 0

        # Check master brokers
        if self.multi_account_manager and self.multi_account_manager.platform_brokers:
            for broker_type, broker in self.multi_account_manager.platform_brokers.items():
                if broker and broker.connected:
                    try:
                        # Check if broker is funded (suppress verbose logging)
                        balance = broker.get_account_balance(verbose=False)
                        if balance >= MINIMUM_FUNDED_BALANCE:
                            positions = broker.get_positions()
                            if positions:
                                brokers_with_positions += 1
                                total_positions += len(positions)
                                self._log_broker_positions(
                                    f"🔷 MASTER - {broker_type.value.upper()}",
                                    balance,
                                    positions
                                )
                            else:
                                logger.info(f"⚪ MASTER - {broker_type.value.upper()}: No open positions")
                    except Exception as e:
                        logger.warning(f"⚠️  Could not get positions for MASTER {broker_type.value.upper()}: {e}")

        # Check user brokers
        if self.multi_account_manager and self.multi_account_manager.user_brokers:
            for user_id, user_broker_dict in self.multi_account_manager.user_brokers.items():
                for broker_type, broker in user_broker_dict.items():
                    if broker and broker.connected:
                        try:
                            # Check if this user broker is funded (suppress verbose logging)
                            balance = broker.get_account_balance(verbose=False)
                            if balance >= MINIMUM_FUNDED_BALANCE:
                                positions = broker.get_positions()
                                if positions:
                                    brokers_with_positions += 1
                                    total_positions += len(positions)
                                    self._log_broker_positions(
                                        f"👤 USER - {user_id.upper()} ({broker_type.value.upper()})",
                                        balance,
                                        positions
                                    )
                                else:
                                    logger.info(f"⚪ USER - {user_id.upper()} ({broker_type.value.upper()}): No open positions")
                        except Exception as e:
                            logger.warning(f"⚠️  Could not get positions for USER {user_id} ({broker_type.value.upper()}): {e}")

        logger.info("=" * 70)
        logger.info(f"📊 SUMMARY: {total_positions} total position(s) across {brokers_with_positions} funded broker(s)")
        logger.info("=" * 70)

    def _log_broker_positions(self, label: str, balance: float, positions: list):
        """
        Helper method to log broker positions in a consistent format.

        Args:
            label: Broker label (e.g., "🔷 MASTER - COINBASE")
            balance: Broker account balance
            positions: List of position dicts
        """
        logger.info(f"{label}:")
        logger.info(f"   💰 Balance: ${balance:,.2f}")
        logger.info(f"   📊 Active Positions: {len(positions)}")
        for pos in positions:
            symbol = pos.get('symbol', 'UNKNOWN')
            quantity = pos.get('quantity', 0)
            logger.info(f"      • {symbol}: {quantity:.8f}")
