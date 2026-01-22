import os
import sys
import time
import random
import queue
import logging
import traceback
from threading import Thread
from typing import Dict, Optional, Tuple
from datetime import datetime
from dotenv import load_dotenv
import pandas as pd

# Import market filters at module level to avoid repeated imports in loops
try:
    from market_filters import check_pair_quality
except ImportError:
    try:
        from bot.market_filters import check_pair_quality
    except ImportError:
        # Graceful fallback if market_filters not available
        check_pair_quality = None

# Import scalar helper for indicator conversions
try:
    from indicators import scalar
except ImportError:
    try:
        from bot.indicators import scalar
    except ImportError:
        # Fallback if indicators.py is not available
        def scalar(x):
            if isinstance(x, (tuple, list)):
                if len(x) == 0:
                    raise ValueError("Cannot convert empty tuple/list to scalar")
                return float(x[0])
            return float(x)

load_dotenv()

logger = logging.getLogger("nija")

# Import BrokerType and AccountType at module level for use throughout the class
# These are needed in _register_kraken_for_retry and other methods outside __init__
try:
    from broker_manager import BrokerType, AccountType
except ImportError:
    try:
        from bot.broker_manager import BrokerType, AccountType
    except ImportError:
        # If broker_manager is not available, define placeholder enums
        # This allows the module to load even if broker_manager is missing
        # NOTE: These values MUST match the enums defined in broker_manager.py
        # Source of truth: bot/broker_manager.py lines 160-177
        from enum import Enum
        
        class BrokerType(Enum):
            COINBASE = "coinbase"
            BINANCE = "binance"
            KRAKEN = "kraken"
            OKX = "okx"
            INTERACTIVE_BROKERS = "interactive_brokers"
            TD_AMERITRADE = "td_ameritrade"
            ALPACA = "alpaca"
            TRADIER = "tradier"
        
        class AccountType(Enum):
            MASTER = "master"
            USER = "user"

# FIX #1: BLACKLIST PAIRS - Disable pairs that are not suitable for strategy
# XRP-USD is PERMANENTLY DISABLED due to negative profitability
# Load additional disabled pairs from environment variable
_env_disabled_pairs = os.getenv('DISABLED_PAIRS', '')
_additional_disabled = [p.strip() for p in _env_disabled_pairs.split(',') if p.strip()]
DISABLED_PAIRS = ["XRP-USD", "XRPUSD", "XRP-USDT"] + _additional_disabled  # Block all XRP pairs - net negative performance

# Time conversion constants
MINUTES_PER_HOUR = 60  # Minutes in one hour (used for time-based calculations)

# OPTIMIZED EXIT FOR LOSING TRADES - Aggressive capital protection
# Exit losing trades after 15 minutes to minimize capital erosion
# Updated from 30 minutes to be more aggressive with loss prevention
MAX_LOSING_POSITION_HOLD_MINUTES = 15  # Exit losing trades after 15 minutes (aggressive protection)

# Configuration constants
# CRITICAL FIX (Jan 10, 2026): Further reduced market scanning to prevent 429/403 rate limit errors
# Coinbase has strict rate limits (~10 req/s burst, lower sustained)
# Instead of scanning all 730 markets every cycle, we batch scan smaller subsets
# RateLimiter enforces 10 req/min (6s between calls), so we must scan fewer markets
MARKET_SCAN_LIMIT = 30   # Scan 30 markets per cycle for better opportunity discovery
                         # This rotates through different markets each cycle
                         # Complete scan of 730 markets takes ~24 cycles (~60 minutes)
                         # Increased from 15 to find 2x more trading opportunities while respecting rate limits
MIN_CANDLES_REQUIRED = 90  # Minimum candles needed for analysis (relaxed from 100 to prevent infinite sell loops)

# Rate limiting constants (prevent 429 errors from Coinbase API)
# UPDATED (Jan 10, 2026): CRITICAL FIX - Aligned delays with RateLimiter to prevent rate limits
# Coinbase rate limits: ~10 requests/second burst, but sustained rate must be much lower
# Real-world testing shows we need to be even more conservative to avoid 403 "too many errors"
# RateLimiter enforces 6s minimum between get_candles calls (10 req/min)
# Manual delay must be >= 6s to avoid conflicts and ensure proper rate limiting
POSITION_CHECK_DELAY = 0.5  # 500ms delay between position checks (was 0.3s)
SELL_ORDER_DELAY = 0.7      # 700ms delay between sell orders (was 0.5s)
MARKET_SCAN_DELAY = 8.0     # 8000ms delay between market scans (increased from 6.5s to 8.0s for better rate limiting)
                            # CRITICAL: Must be >= 7.5s to align with RateLimiter (8 req/min for get_candles)
                            # The 0.5s buffer (8.0s vs 7.5s) accounts for jitter and processing time
                            # At 8.0s delay, we scan at ~0.125 req/s which prevents both 429 and 403 errors
                            # At 5-15 markets per cycle with 8.0s delay, scanning takes 40-120 seconds
                            # This conservative rate ensures API key never gets temporarily blocked
                            
# Market scanning rotation (prevents scanning same markets every cycle)
# UPDATED (Jan 10, 2026): Adaptive batch sizing to prevent API rate limiting
MARKET_BATCH_SIZE_MIN = 10   # Start with 10 markets per cycle on fresh start (gradual warmup)
MARKET_BATCH_SIZE_MAX = 30  # Maximum markets to scan per cycle after warmup
MARKET_BATCH_WARMUP_CYCLES = 3  # Number of cycles to warm up before using max batch size
MARKET_ROTATION_ENABLED = True  # Rotate through different market batches each cycle

# Exit strategy constants (no entry price required)
# CRITICAL FIX (Jan 13, 2026): Aggressive RSI thresholds to sell faster
MIN_POSITION_VALUE = 1.0  # Auto-exit positions under this USD value
RSI_OVERBOUGHT_THRESHOLD = 55  # Exit when RSI exceeds this (lock gains) - LOWERED from 60 for faster profit-taking
RSI_OVERSOLD_THRESHOLD = 45  # Exit when RSI below this (cut losses) - RAISED from 40 for faster loss-cutting
DEFAULT_RSI = 50  # Default RSI value when indicators unavailable

# Time-based exit thresholds (prevent indefinite holding)
# CRITICAL FIX (Jan 19, 2026): IMMEDIATE EXIT FOR ALL LOSING TRADES
# LOSING TRADES: EXIT after 30 minutes to allow recovery (changed from immediate)
# PROFITABLE TRADES: Can run up to 24 hours to capture full gains
# NIJA is for PROFIT - give positions time to develop and capture gains
MAX_POSITION_HOLD_HOURS = 24  # Auto-exit ALL positions held longer than 24 hours (daily strategy)
MAX_POSITION_HOLD_EMERGENCY = 48  # EMERGENCY exit - force sell ALL positions after 48 hours (absolute failsafe)
STALE_POSITION_WARNING_HOURS = 12  # Warn about positions held this long (12 hours)
# Unsellable position retry timeout (prevent permanent blocking)
# After this many hours, retry selling positions that were previously marked unsellable
# This handles cases where position grew enough to be sellable, or API errors were temporary
UNSELLABLE_RETRY_HOURS = 12  # Retry selling "unsellable" positions after 12 hours (half of max hold time)
# ZOMBIE POSITION DETECTION: Disabled - positions need time to develop
# Auto-imported positions are tracked properly with entry prices now
ZOMBIE_POSITION_HOURS = 24.0  # Increased from 1 hour to 24 hours to allow normal price movement
ZOMBIE_PNL_THRESHOLD = 0.01  # Consider position "stuck" if abs(P&L) < this % (0.01%)

# Profit target thresholds (stepped exits) - FEE-AWARE + ULTRA AGGRESSIVE V7.3
# Updated Jan 12, 2026 - PROFITABILITY FIX: Aggressive profit-taking to lock gains
# CRITICAL: With small positions, we need FASTER exits to lock gains
# Default targets are for Coinbase (1.4% fees)
# Coinbase fees are ~1.4%, so minimum 1.5% needed for net profit
# Kraken fees are ~0.36%, so lower targets are profitable
# Strategy: Exit FULL position at FIRST target hit, checking from HIGHEST to LOWEST
# This prioritizes larger gains while providing emergency exit near breakeven
PROFIT_TARGETS = [
    (1.5, "Profit target +1.5% (Net ~0.1% after fees) - GOOD"),          # Check first - lock profits quickly
    (1.2, "Profit target +1.2% (Net ~-0.2% after fees) - ACCEPTABLE"),   # Check second - accept small loss vs reversal
    (1.0, "Profit target +1.0% (Net ~-0.4% after fees) - EMERGENCY"),    # Emergency exit to prevent larger loss
]

# BROKER-SPECIFIC PROFIT TARGETS (Jan 19, 2026)
# Different brokers have different fee structures, requiring different profit targets
# These ensure NET profitability after fees for each broker
PROFIT_TARGETS_KRAKEN = [
    (1.0, "Profit target +1.0% (Net +0.64% after 0.36% fees) - EXCELLENT"),  # Kraken: Net positive
    (0.7, "Profit target +0.7% (Net +0.34% after fees) - GOOD"),             # Still profitable
    (0.5, "Profit target +0.5% (Net +0.14% after fees) - MINIMAL"),          # Tight margin
]

PROFIT_TARGETS_COINBASE = [
    (1.5, "Profit target +1.5% (Net +0.1% after 1.4% fees) - GOOD"),         # Coinbase: Barely profitable
    (1.2, "Profit target +1.2% (Net -0.2% after fees) - ACCEPTABLE"),        # Accept small loss vs reversal
    (1.0, "Profit target +1.0% (Net -0.4% after fees) - EMERGENCY"),         # Better than -1% stop
]

# CRITICAL FIX (Jan 13, 2026): Tightened profit targets to lock gains faster
# NIJA is for PROFIT - take gains quickly before reversals
# Fee structure: See fee_aware_config.py - MARKET_ORDER_ROUND_TRIP = 1.4% (default)
# First target (1.5%) is NET profitable after fees: 1.5% - 1.4% = +0.1% profit
# Second target (1.2%) accepts small loss to prevent larger reversal: 1.2% - 1.4% = -0.2% (vs -1.0% stop)
# Third target (1.0%) is emergency exit: 1.0% - 1.4% = -0.4% (still better than -1.0% stop loss)
# The bot checks targets from TOP to BOTTOM, so it exits at 1.5% if available, 1.2% if not, etc.

# FIX #3: Minimum Profit Threshold
# Calculate required profit = spread + fees + buffer before allowing exit
# Coinbase: ~0.6% taker fee + ~0.2% spread = 0.8% one way, 1.6% round-trip
MIN_PROFIT_SPREAD = 0.002  # 0.2% estimated spread cost
MIN_PROFIT_FEES = 0.012  # 1.2% estimated fees (0.6% per side)
MIN_PROFIT_BUFFER = 0.002  # 0.2% safety buffer
MIN_PROFIT_THRESHOLD = 0.016  # 1.6% minimum profit (spread + fees + buffer)

# Stop loss thresholds - ULTRA-AGGRESSIVE (V7.4 FIX - Jan 19, 2026)
# CRITICAL: Exit ANY losing trade IMMEDIATELY (P&L < 0%)
# These thresholds are FAILSAFES only - primary exit is immediate on any loss
# Jan 19, 2026: Changed to immediate exit on ANY loss per user requirement
# Jan 13, 2026: Tightened to -1.0% to cut losses IMMEDIATELY
# Jan 19, 2026: 3-TIER STOP-LOSS SYSTEM for Kraken small balances
# Tier 1: Primary trading stop (-0.6% to -0.8%) - Real stop-loss for risk management
# Tier 2: Emergency micro-stop (-0.01%) - Logic failure prevention (not a trading stop)
# Tier 3: Catastrophic failsafe (-5.0%) - Last resort protection

# TIER 1: PRIMARY TRADING STOP-LOSS (Kraken small balances)
# For small Kraken accounts, use -0.6% to -0.8% as the PRIMARY stop-loss
# This accounts for Kraken's lower fees (0.36% round-trip) vs Coinbase (1.4%)
STOP_LOSS_PRIMARY_KRAKEN = -0.008  # -0.8% for Kraken small balances (spread + fees + buffer)
STOP_LOSS_PRIMARY_KRAKEN_MIN = -0.006  # -0.6% minimum (tightest acceptable)
STOP_LOSS_PRIMARY_KRAKEN_MAX = -0.008  # -0.8% maximum (conservative)

# TIER 2: EMERGENCY MICRO-STOP (Logic failure prevention)
# This is NOT a trading stop - it's a failsafe to prevent logic failures
# Examples: imported positions without entry price, calculation errors, data corruption
# Terminology: "Emergency micro-stop to prevent logic failures (not a trading stop)"
STOP_LOSS_MICRO = -0.01  # -1% emergency micro-stop for logic failure prevention
STOP_LOSS_WARNING = -0.01  # Same as micro-stop - warn immediately
STOP_LOSS_THRESHOLD = -0.01  # Legacy threshold (same as micro-stop)

# TIER 3: CATASTROPHIC FAILSAFE
# Last resort protection - should NEVER be reached in normal operation
# NORMALIZED FORMAT: -0.05 = -5% (fractional format)
STOP_LOSS_EMERGENCY = -0.05  # EMERGENCY exit at -5% loss (FAILSAFE - absolute last resort)

# OPTIONAL ENHANCEMENT: Minimum loss floor
# Ignore very small losses to reduce noise and prevent overtrading
MIN_LOSS_FLOOR = -0.0025  # -0.25% - ignore losses smaller than this

# Auto-import safety default constants (FIX #1 - Jan 19, 2026)
# When auto-importing orphaned positions without real entry price, use safety default
# This creates immediate negative P&L to flag position as losing for aggressive exit
SAFETY_DEFAULT_ENTRY_MULTIPLIER = 1.01  # Assume entry was 1% higher than current price
                                          # Creates -0.99% immediate P&L, flagging as loser

# Position management constants - PROFITABILITY FIX (Dec 28, 2025)
# Updated Jan 20, 2026: Raised minimum to $5 for safer trade sizing
# Updated Jan 21, 2026: OPTION 3 (BEST LONG-TERM) - Dynamic minimum based on balance
# ⚠️ CRITICAL WARNING: Small positions are unprofitable due to fees (~1.4% round-trip)
# With $5+ positions, trades have better chance of profitability after fees
# This ensures better trading outcomes and quality over quantity
# STRONG RECOMMENDATION: Fund account to $50+ for optimal trading outcomes
MAX_POSITIONS_ALLOWED = 8  # Maximum concurrent positions (including protected/micro positions)

# OPTION 3 (BEST LONG-TERM): Dynamic minimum based on balance
# MIN_TRADE_USD = max(2.00, balance * 0.15)
# This scales automatically with account size:
# - $13 account: min trade = $2.00 (15% would be $1.95)
# - $20 account: min trade = $3.00 (15% of $20)
# - $50 account: min trade = $7.50 (15% of $50)
# - $100 account: min trade = $15.00 (15% of $100)
BASE_MIN_POSITION_SIZE_USD = 2.0  # Floor minimum ($2 for very small accounts)
DYNAMIC_POSITION_SIZE_PCT = 0.15  # 15% of balance as minimum (OPTION 3)

def get_dynamic_min_position_size(balance: float) -> float:
    """
    Calculate dynamic minimum position size based on account balance.
    OPTION 3 (BEST LONG-TERM): MIN_TRADE_USD = max(2.00, balance * 0.15)
    
    Args:
        balance: Current account balance in USD
        
    Returns:
        Minimum position size in USD
        
    Raises:
        ValueError: If balance is negative
    """
    if balance < 0:
        raise ValueError(f"Balance cannot be negative: {balance}")
    
    return max(BASE_MIN_POSITION_SIZE_USD, balance * DYNAMIC_POSITION_SIZE_PCT)

# DEPRECATED: Use get_dynamic_min_position_size() instead
# This constant is maintained for backward compatibility only
MIN_POSITION_SIZE_USD = BASE_MIN_POSITION_SIZE_USD  # Legacy fallback (use get_dynamic_min_position_size() instead)
MIN_BALANCE_TO_TRADE_USD = 2.0  # Minimum account balance to allow trading (lowered from $5 to support small accounts)

# FIX #3 (Jan 20, 2026): Kraken-specific minimum thresholds
# Kraken WILL NOT trade if balance < $25 OR min order size not met OR fees make position < min notional
MIN_KRAKEN_BALANCE = 25.0  # Minimum balance for Kraken to allow trading
MIN_POSITION_SIZE = 1.25   # 5% of $25 - minimum position size for Kraken

# BROKER PRIORITY SYSTEM (Jan 22, 2025)
# Define entry broker priority for BUY orders
# Brokers will be selected in this order if eligible (not in EXIT_ONLY mode and balance >= minimum)
# Coinbase automatically falls to bottom priority if balance < $25
ENTRY_BROKER_PRIORITY = [
    BrokerType.KRAKEN,
    BrokerType.OKX,
    BrokerType.BINANCE,
    BrokerType.COINBASE,
]

# Minimum balance thresholds for broker eligibility
BROKER_MIN_BALANCE = {
    BrokerType.COINBASE: 25.0,  # Coinbase requires $25 minimum for new entries
    BrokerType.KRAKEN: 25.0,    # Kraken requires $25 minimum
    BrokerType.OKX: 10.0,       # Lower minimum for OKX
    BrokerType.BINANCE: 10.0,   # Lower minimum for Binance
}

def call_with_timeout(func, args=(), kwargs=None, timeout_seconds=30):
    """
    Execute a function with a timeout. Returns (result, error).
    If timeout occurs, returns (None, TimeoutError).
    Default timeout is 30 seconds to accommodate production API latency.
    """
    if kwargs is None:
        kwargs = {}
    result_queue = queue.Queue()

    def worker():
        try:
            result = func(*args, **kwargs)
            result_queue.put((True, result))
        except Exception as e:
            result_queue.put((False, e))

    t = Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout_seconds)

    if t.is_alive():
        return None, TimeoutError(f"Operation timed out after {timeout_seconds}s")

    try:
        ok, value = result_queue.get_nowait()
        return (value, None) if ok else (None, value)
    except queue.Empty:
        return None, Exception("No result returned from worker")

# Add bot directory to path if running from root
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Optional market price helper; safe fallback if unavailable
try:
    from bot.market_data import get_current_price  # type: ignore
except Exception:
    def get_current_price(symbol: str):
        """Fallback price lookup (returns None if unavailable)."""
        return None

class TradingStrategy:
    """Production Trading Strategy - Coinbase APEX v7.1.

    Encapsulates the full APEX v7.1 trading strategy with position cap enforcement.
    Integrates market scanning, entry/exit logic, risk management, and automated
    position limit enforcement.
    """

    def __init__(self):
        """Initialize production strategy with multi-broker support."""
        logger.info("Initializing TradingStrategy (APEX v7.1 - Multi-Broker Mode)...")
        
        # FIX #1: Initialize portfolio state manager for total equity tracking
        try:
            from portfolio_state import get_portfolio_manager
            self.portfolio_manager = get_portfolio_manager()
            logger.info("✅ Portfolio state manager initialized - using total equity for sizing")
        except ImportError:
            logger.warning("⚠️ Portfolio state manager not available - falling back to cash-based sizing")
            self.portfolio_manager = None
        
        # FIX #2: Initialize forced stop-loss executor
        try:
            from forced_stop_loss import create_forced_stop_loss
            # Will be set to actual broker instance after connection
            self.forced_stop_loss = None
            logger.info("✅ Forced stop-loss module loaded")
        except ImportError:
            logger.warning("⚠️ Forced stop-loss module not available")
            self.forced_stop_loss = None
        
        # Track positions that can't be sold (too small/dust) to avoid infinite retry loops
        # NEW (Jan 16, 2026): Track with timestamps to allow retry after timeout
        self.unsellable_positions = {}  # Dict of symbol -> timestamp when marked unsellable
        self.unsellable_retry_timeout = UNSELLABLE_RETRY_HOURS * 3600  # Convert hours to seconds
        
        # Track failed broker connections for error reporting
        self.failed_brokers = {}  # Dict of BrokerType -> broker instance for failed connections
        
        # Market rotation state (prevents scanning same markets every cycle)
        self.market_rotation_offset = 0  # Tracks which batch of markets to scan next
        self.all_markets_cache = []      # Cache of all available markets
        self.markets_cache_time = 0      # Timestamp of last market list refresh
        self.MARKETS_CACHE_TTL = 3600    # Refresh market list every hour
        
        # Rate limiting warmup state (prevents API bans on startup)
        self.cycle_count = 0             # Track number of cycles for warmup
        self.api_health_score = 100      # 0-100, degrades on errors, recovers on success
        
        # Candle data cache (prevents duplicate API calls for same market/timeframe)
        self.candle_cache = {}           # {symbol: (timestamp, candles_data)}
        self.CANDLE_CACHE_TTL = 150      # Cache candles for 2.5 minutes (one cycle)
        
        # Initialize advanced trading features (progressive targets, exchange profiles, capital allocation)
        self.advanced_manager = None
        self._init_advanced_features()
        
        # Initialize credential health monitoring to detect credential loss
        # This helps diagnose recurring disconnection issues
        try:
            from credential_health_monitor import start_credential_monitoring
            logger.info("🔍 Starting credential health monitoring...")
            self.credential_monitor = start_credential_monitoring(check_interval=300)  # Check every 5 minutes
            logger.info("   ✅ Credential monitoring active (checks every 5 minutes)")
        except Exception as e:
            logger.warning(f"⚠️  Could not start credential monitoring: {e}")
            self.credential_monitor = None
        
        try:
            # Lazy imports to avoid circular deps and allow fallback
            # Note: BrokerType and AccountType are now imported at module level
            from broker_manager import (
                BrokerManager, CoinbaseBroker, KrakenBroker, 
                OKXBroker, BinanceBroker, AlpacaBroker
            )
            from multi_account_broker_manager import multi_account_broker_manager
            from position_cap_enforcer import PositionCapEnforcer
            from nija_apex_strategy_v71 import NIJAApexStrategyV71
            
            # Initialize multi-account broker manager for user-specific trading
            logger.info("=" * 70)
            logger.info("🌐 MULTI-ACCOUNT TRADING MODE ACTIVATED")
            logger.info("=" * 70)
            logger.info("   Master account + User accounts trading independently")
            logger.info("=" * 70)
            
            # Use the global singleton instance to ensure failed connection tracking persists
            self.multi_account_manager = multi_account_broker_manager
            self.broker_manager = BrokerManager()  # Keep for backward compatibility
            connected_brokers = []
            user_brokers = []
            
            # Add startup delay to avoid immediate rate limiting on restart
            # CRITICAL (Jan 2026): Increased to 45s to ensure API rate limits fully reset
            # Previous 30s delay was still causing rate limit issues in production
            # Coinbase appears to have a ~30-60 second cooldown period after 403 errors
            # Combined with improved retry logic (10 attempts, 15s base delay with 120s cap),
            # this gives the bot multiple chances to recover from temporary API blocks
            startup_delay = 45
            logger.info(f"⏱️  Waiting {startup_delay}s before connecting to avoid rate limits...")
            time.sleep(startup_delay)
            logger.info("✅ Startup delay complete, beginning broker connections...")
            
            # Try to connect Coinbase (primary broker) - MASTER ACCOUNT
            logger.info("📊 Attempting to connect Coinbase Advanced Trade (MASTER)...")
            try:
                coinbase = CoinbaseBroker()
                if coinbase.connect():
                    self.broker_manager.add_broker(coinbase)
                    # Manually register in multi_account_manager (reuse same instance)
                    self.multi_account_manager.master_brokers[BrokerType.COINBASE] = coinbase
                    connected_brokers.append("Coinbase")
                    logger.info("   ✅ Coinbase MASTER connected")
                    logger.info("   ✅ Coinbase registered as MASTER broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  Coinbase MASTER connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  Coinbase MASTER error: {e}")
            
            # Add delay between broker connections to avoid rate limiting
            time.sleep(2.0)  # Increased from 0.5s to 2.0s
            
            # Try to connect Kraken Pro - MASTER ACCOUNT
            logger.info("📊 Attempting to connect Kraken Pro (MASTER)...")
            kraken = None  # Initialize to ensure variable exists for exception handler
            try:
                kraken = KrakenBroker(account_type=AccountType.MASTER)
                connection_successful = kraken.connect()
                
                # CRITICAL FIX (Jan 17, 2026): Allow Kraken to start even if connection test fails
                # This prevents a single connection failure from permanently disabling Kraken trading
                # The trading loop will retry connections in the background and self-heal
                # This is similar to how other brokers handle transient connection issues
                if connection_successful:
                    self.broker_manager.add_broker(kraken)
                    # Manually register in multi_account_manager (reuse same instance)
                    self.multi_account_manager.master_brokers[BrokerType.KRAKEN] = kraken
                    connected_brokers.append("Kraken")
                    logger.info("   ✅ Kraken MASTER connected")
                    logger.info("   ✅ Kraken registered as MASTER broker in multi-account manager")
                    
                    # COPY TRADING INTEGRATION: Initialize and wrap Kraken broker
                    # CRITICAL FIX (Jan 18, 2026): Track if copy trading initialized users
                    # to prevent duplicate initialization in connect_users_from_config()
                    try:
                        from bot.kraken_copy_trading import (
                            initialize_copy_trading_system,
                            wrap_kraken_broker_for_copy_trading
                        )
                        
                        # Initialize copy trading system (master + users)
                        if initialize_copy_trading_system():
                            # Wrap the broker to enable automatic copy trading
                            wrap_kraken_broker_for_copy_trading(kraken)
                            logger.info("   ✅ Kraken copy trading system activated")
                            # Notify multi_account_manager that Kraken users are handled by copy trading
                            self.multi_account_manager.kraken_copy_trading_active = True
                        else:
                            logger.warning("   ⚠️  Kraken copy trading initialization failed - trades will execute on MASTER only")
                    except ImportError as import_err:
                        logger.warning(f"   ⚠️  Kraken copy trading module not available: {import_err}")
                    except Exception as copy_err:
                        logger.error(f"   ❌ Kraken copy trading setup error: {copy_err}")
                        import traceback
                        logger.error(traceback.format_exc())
                else:
                    # Connection test failed, but still register broker for background retry
                    # The trading loop will handle the disconnected state and retry automatically
                    logger.warning("   ⚠️  Kraken MASTER connection test failed, will retry in background")
                    logger.warning("   📌 Kraken broker initialized - trading loop will attempt reconnection")
                    self._log_broker_independence_message()
                    
                    # Use helper method to register for retry
                    self._register_kraken_for_retry(kraken)
                    
            except Exception as e:
                # CRITICAL FIX (Jan 17, 2026): Handle exceptions consistently with connection failures
                # Even if broker initialization throws an exception, register it for retry if possible
                # This maintains consistent self-healing behavior across all failure types
                if kraken is not None:
                    logger.warning(f"   ⚠️  Kraken MASTER initialization error: {e}")
                    logger.warning("   📌 Kraken broker will be registered for background retry")
                    self._log_broker_independence_message()
                    
                    # Use helper method to register for retry
                    self._register_kraken_for_retry(kraken)
                else:
                    # Broker object was never created - can't retry
                    logger.error(f"   ❌ Kraken MASTER initialization failed: {e}")
                    logger.error("   ❌ Kraken will not be available for trading")
                    self._log_broker_independence_message()
            
            # Add delay between broker connections
            time.sleep(0.5)
            
            # Try to connect OKX - MASTER ACCOUNT
            logger.info("📊 Attempting to connect OKX (MASTER)...")
            try:
                okx = OKXBroker()
                if okx.connect():
                    self.broker_manager.add_broker(okx)
                    # Manually register in multi_account_manager (reuse same instance)
                    self.multi_account_manager.master_brokers[BrokerType.OKX] = okx
                    connected_brokers.append("OKX")
                    logger.info("   ✅ OKX MASTER connected")
                    logger.info("   ✅ OKX registered as MASTER broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  OKX MASTER connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  OKX MASTER error: {e}")
            
            # Add delay between broker connections
            time.sleep(0.5)
            
            # Try to connect Binance - MASTER ACCOUNT
            logger.info("📊 Attempting to connect Binance (MASTER)...")
            try:
                binance = BinanceBroker()
                if binance.connect():
                    self.broker_manager.add_broker(binance)
                    # Manually register in multi_account_manager (reuse same instance)
                    self.multi_account_manager.master_brokers[BrokerType.BINANCE] = binance
                    connected_brokers.append("Binance")
                    logger.info("   ✅ Binance MASTER connected")
                    logger.info("   ✅ Binance registered as MASTER broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  Binance MASTER connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  Binance MASTER error: {e}")
            
            # Add delay between broker connections
            time.sleep(0.5)
            
            # Try to connect Alpaca (for stocks) - MASTER ACCOUNT
            logger.info("📊 Attempting to connect Alpaca (MASTER - Paper Trading)...")
            try:
                alpaca = AlpacaBroker()
                if alpaca.connect():
                    self.broker_manager.add_broker(alpaca)
                    # Manually register in multi_account_manager (reuse same instance)
                    self.multi_account_manager.master_brokers[BrokerType.ALPACA] = alpaca
                    connected_brokers.append("Alpaca")
                    logger.info("   ✅ Alpaca MASTER connected")
                    logger.info("   ✅ Alpaca registered as MASTER broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  Alpaca MASTER connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  Alpaca MASTER error: {e}")
            
            # Add delay before user account connections to ensure master account
            # connection has completed and nonce ranges are separated
            # CRITICAL (Jan 14, 2026): Increased from 2.0s to 5.0s to prevent Kraken nonce conflicts
            # Master Kraken connection may still be using nonces in the current time window.
            # User connections should wait long enough to ensure non-overlapping nonce ranges.
            time.sleep(5.0)
            
            # Connect User Accounts - Load from config files
            logger.info("=" * 70)
            logger.info("👤 CONNECTING USER ACCOUNTS FROM CONFIG FILES")
            logger.info("=" * 70)
            
            # Use the new config-based user loading system
            connected_user_brokers = self.multi_account_manager.connect_users_from_config()
            
            # Track which users were successfully connected
            user_brokers = []
            if connected_user_brokers:
                for brokerage, user_ids in connected_user_brokers.items():
                    for user_id in user_ids:
                        user_brokers.append(f"{user_id}: {brokerage.title()}")
            
            logger.info("=" * 70)
            logger.info("✅ Broker connection phase complete")
            if connected_brokers or user_brokers:
                if connected_brokers:
                    logger.info(f"✅ MASTER ACCOUNT BROKERS: {', '.join(connected_brokers)}")
                    
                    # HELPFUL TIP: If only Coinbase is connected, suggest enabling Kraken
                    # Can be suppressed by setting SUPPRESS_SINGLE_EXCHANGE_WARNING=true
                    suppress_warning = os.getenv("SUPPRESS_SINGLE_EXCHANGE_WARNING", "false").lower() in ("true", "1", "yes")
                    if len(connected_brokers) == 1 and "Coinbase" in connected_brokers and not suppress_warning:
                        logger.warning("=" * 70)
                        logger.warning("⚠️  SINGLE EXCHANGE TRADING - CONSIDER ENABLING KRAKEN")
                        logger.warning("=" * 70)
                        logger.warning("You're trading on Coinbase only, which may cause rate limiting.")
                        logger.warning("Enable Kraken to distribute load across multiple exchanges:")
                        logger.warning("")
                        logger.warning("1. Get API credentials from https://www.kraken.com/u/security/api")
                        logger.warning("2. Set environment variables:")
                        logger.warning("   KRAKEN_MASTER_API_KEY=<your-api-key>")
                        logger.warning("   KRAKEN_MASTER_API_SECRET=<your-api-secret>")
                        logger.warning("3. Restart the bot")
                        logger.warning("")
                        logger.warning("Benefits:")
                        logger.warning("✓ Reduced API rate limiting (load split across exchanges)")
                        logger.warning("✓ More resilient trading (if one exchange has issues)")
                        logger.warning("✓ Access to different cryptocurrency pairs")
                        logger.warning("")
                        logger.warning("📖 Setup Guide: KRAKEN_QUICK_START.md")
                        logger.warning("📖 Multi-Exchange Trading: MULTI_EXCHANGE_TRADING_GUIDE.md")
                        logger.warning("To suppress this warning, set SUPPRESS_SINGLE_EXCHANGE_WARNING=true")
                        logger.warning("=" * 70)
                    if len(connected_brokers) == 1 and "Coinbase" in connected_brokers:
                        broker = connected_brokers[0]  # Get the single connected broker
                        logger.warning(f"⚠️  Single exchange trading ({broker} only). Consider enabling Kraken for better resilience and reduced rate limiting.")
                        logger.info("📖 To enable Kraken: See KRAKEN_QUICK_START.md for step-by-step instructions.")
                if user_brokers:
                    logger.info(f"👥 USER ACCOUNT BROKERS: {', '.join(user_brokers)}")
                
                # CRITICAL: Master and users are COMPLETELY INDEPENDENT
                # Master balance is ONLY for master account - users don't affect it
                master_balance = self.broker_manager.get_total_balance()
                
                # Get user balances dynamically from multi_account_manager (for reporting only)
                user_total_balance = 0.0
                if self.multi_account_manager.user_brokers:
                    for user_id, user_broker_dict in self.multi_account_manager.user_brokers.items():
                        for broker_type, broker in user_broker_dict.items():
                            try:
                                if broker.connected:
                                    user_balance = broker.get_account_balance()
                                    user_total_balance += user_balance
                            except Exception as e:
                                logger.debug(f"Could not get balance for {user_id}: {e}")
                
                # Report balances separately - DO NOT combine them
                logger.info(f"💰 MASTER ACCOUNT BALANCE: ${master_balance:,.2f}")
                if user_total_balance > 0:
                    logger.info(f"💰 USER ACCOUNTS BALANCE (INDEPENDENT): ${user_total_balance:,.2f}")
                
                # CRITICAL: Update advanced manager with ONLY master balance
                # Users are completely independent and don't affect master's capital allocation
                if self.advanced_manager and master_balance > 0:
                    try:
                        self.advanced_manager.capital_allocator.update_total_capital(master_balance)
                        logger.info(f"   ✅ Master capital allocation: ${master_balance:,.2f}")
                    except Exception as e:
                        logger.warning(f"   Failed to update master capital allocation: {e}")
                
                # FIX #1: Select primary master broker with Kraken promotion logic
                # CRITICAL: If Coinbase is in exit_only mode or has insufficient balance, promote Kraken to primary
                # Only call this after all brokers are connected to make an informed decision
                self.broker_manager.select_primary_master_broker()
                
                # Get the primary broker from broker_manager
                # This is used for master account trading
                self.broker = self.broker_manager.get_primary_broker()
                if self.broker:
                    # Log the primary master broker with explicit reason if it was switched
                    broker_name = self.broker.broker_type.value.upper()
                    
                    # Check if any other broker is in exit_only mode (indicates a switch happened)
                    exit_only_brokers = []
                    for broker_type, broker in self.multi_account_manager.master_brokers.items():
                        if broker and broker.connected and broker.exit_only_mode:
                            exit_only_brokers.append(broker_type.value.upper())
                    
                    if exit_only_brokers and broker_name == "KRAKEN":
                        # Kraken was promoted because another broker is exit-only
                        logger.info(f"📌 Primary master broker: {broker_name} ({', '.join(exit_only_brokers)} EXIT-ONLY)")
                    else:
                        logger.info(f"📌 Primary master broker: {broker_name}")
                    
                    # FIX #2: Initialize forced stop-loss with the connected broker
                    if self.forced_stop_loss is None:
                        try:
                            from forced_stop_loss import create_forced_stop_loss
                            self.forced_stop_loss = create_forced_stop_loss(self.broker)
                            logger.info("✅ Forced stop-loss executor initialized with master broker")
                        except Exception as e:
                            logger.warning(f"⚠️ Could not initialize forced stop-loss: {e}")
                    
                    # FIX #3: Initialize master portfolio state using SUM of ALL master brokers
                    # CRITICAL: Master portfolio must use total_master_equity = sum(all master brokers)
                    # Do NOT just use primary broker's balance - this ignores capital in other brokers
                    if self.portfolio_manager:
                        try:
                            # Calculate total cash/balance across ALL connected master brokers
                            total_master_cash = 0.0
                            master_broker_balances = []
                            
                            for broker_type, broker in self.multi_account_manager.master_brokers.items():
                                if broker and broker.connected:
                                    try:
                                        broker_balance = broker.get_account_balance()
                                        total_master_cash += broker_balance
                                        master_broker_balances.append(f"{broker_type.value}: ${broker_balance:.2f}")
                                        logger.info(f"   💰 Master broker {broker_type.value}: ${broker_balance:.2f}")
                                    except Exception as broker_err:
                                        logger.warning(f"   ⚠️ Could not get balance from {broker_type.value}: {broker_err}")
                            
                            if total_master_cash > 0:
                                # Initialize/update master portfolio with TOTAL cash from all brokers
                                # Note: portfolio.total_equity will be cash + position values
                                self.master_portfolio = self.portfolio_manager.initialize_master_portfolio(total_master_cash)
                                logger.info("=" * 70)
                                logger.info("✅ MASTER PORTFOLIO INITIALIZED")
                                logger.info("=" * 70)
                                for balance_str in master_broker_balances:
                                    logger.info(f"   {balance_str}")
                                logger.info(f"   TOTAL MASTER CASH: ${total_master_cash:.2f}")
                                logger.info(f"   TOTAL MASTER EQUITY: ${self.master_portfolio.total_equity:.2f}")
                                logger.info("=" * 70)
                            else:
                                logger.warning("⚠️ No master broker balances available - portfolio not initialized")
                                self.master_portfolio = None
                        except Exception as e:
                            logger.warning(f"⚠️ Could not initialize master portfolio: {e}")
                            self.master_portfolio = None
                    else:
                        self.master_portfolio = None
                else:
                    logger.warning("⚠️  No primary master broker available")
                    self.master_portfolio = None
            else:
                logger.error("❌ NO BROKERS CONNECTED - Running in monitor mode")
                self.broker = None
            
            # Log clear trading status summary
            logger.info("=" * 70)
            logger.info("📊 ACCOUNT TRADING STATUS SUMMARY")
            logger.info("=" * 70)
            
            # Count active trading accounts
            active_master_count = 1 if self.broker else 0
            active_user_count = 0
            
            # Master account status
            if self.broker:
                logger.info(f"✅ MASTER ACCOUNT: TRADING (Broker: {self.broker.broker_type.value.upper()})")
            else:
                logger.info("❌ MASTER ACCOUNT: NOT TRADING (No broker connected)")
            
            # User account status - dynamically load from config
            try:
                from config.user_loader import get_user_config_loader
                user_loader = get_user_config_loader()
                enabled_users = user_loader.get_all_enabled_users()
                
                if enabled_users:
                    for user in enabled_users:
                        # FIX #1: Check if this is a Kraken user managed by copy trading system
                        is_kraken = user.broker_type.upper() == "KRAKEN"
                        is_copy_trader = getattr(user, 'copy_from_master', False)
                        kraken_copy_active = getattr(self.multi_account_manager, 'kraken_copy_trading_active', False)
                        
                        # If Kraken user is managed by copy trading, show special status and skip re-evaluation
                        if is_kraken and is_copy_trader and kraken_copy_active:
                            logger.info(f"✅ USER: {user.name}: ACTIVE (COPY TRADING) (Broker: KRAKEN)")
                            # Add disabled symbols info for Kraken copy traders
                            disabled_symbols = getattr(user, 'disabled_symbols', [])
                            if disabled_symbols:
                                disabled_str = ", ".join(disabled_symbols)
                                logger.info(f"   ℹ️  Disabled symbols: {disabled_str} (configured for copy trading)")
                            active_user_count += 1
                            continue  # Skip re-evaluation for copy trading users
                        
                        # Check if this user is actually connected
                        user_broker = self.multi_account_manager.get_user_broker(
                            user.user_id, 
                            BrokerType[user.broker_type.upper()]
                        )
                        
                        if user_broker and user_broker.connected:
                            logger.info(f"✅ USER: {user.name}: TRADING (Broker: {user.broker_type.upper()})")
                            active_user_count += 1
                        else:
                            # Check if credentials are configured
                            has_creds = self.multi_account_manager.user_has_credentials(
                                user.user_id,
                                BrokerType[user.broker_type.upper()]
                            )
                            if has_creds:
                                # Credentials configured but connection failed
                                logger.info(f"❌ USER: {user.name}: NOT TRADING (Broker: {user.broker_type.upper()}, Connection failed)")
                            else:
                                # Credentials not configured - informational, not an error
                                logger.info(f"⚪ USER: {user.name}: NOT CONFIGURED (Broker: {user.broker_type.upper()}, Credentials not set)")
                else:
                    logger.info("⚪ No user accounts configured")
            except Exception as e:
                logger.warning(f"⚠️  Could not load user status from config: {e}")
                # Fallback: show status based on connected user brokers
                if self.multi_account_manager.user_brokers:
                    for user_id, user_broker_dict in self.multi_account_manager.user_brokers.items():
                        for broker_type, broker in user_broker_dict.items():
                            if broker.connected:
                                logger.info(f"✅ USER: {user_id}: TRADING (Broker: {broker_type.value.upper()})")
                                active_user_count += 1
                            else:
                                logger.info(f"❌ USER: {user_id}: NOT TRADING (Broker: {broker_type.value.upper()}, Connection failed)")
            
            logger.info("=" * 70)
            
            # Overall status and recommendations
            total_active = active_master_count + active_user_count
            if total_active > 0:
                logger.info(f"🚀 TRADING ACTIVE: {total_active} account(s) ready")
                logger.info("")
                logger.info("Next steps:")
                logger.info("   • Bot will start scanning markets in ~45 seconds")
                logger.info("   • Trades will execute automatically when signals are found")
                logger.info("   • Monitor logs with: tail -f nija.log")
                logger.info("")
                if active_master_count == 0:
                    logger.warning("⚠️  Master account not trading - only user accounts active")
                if active_user_count == 0:
                    logger.info("💡 Tip: Add user accounts to enable multi-user trading")
                    logger.info("   See config/users/ for user configuration")
            else:
                logger.error("❌ NO TRADING ACTIVE - All connection attempts failed")
                logger.error("")
                logger.error("Troubleshooting:")
                logger.error("   1. Run: python3 validate_all_env_vars.py")
                logger.error("   2. Fix any missing credentials")
                logger.error("   3. Restart the bot")
                logger.error("   4. See BROKER_CONNECTION_TROUBLESHOOTING.md for help")
            
            logger.info("=" * 70)
            
            # Initialize independent broker trader for multi-broker support
            try:
                from independent_broker_trader import IndependentBrokerTrader
                self.independent_trader = IndependentBrokerTrader(
                    self.broker_manager, 
                    self,
                    self.multi_account_manager  # Pass multi-account manager for user trading
                )
                logger.info("✅ Independent broker trader initialized")
            except Exception as indie_err:
                logger.warning(f"⚠️  Independent trader initialization failed: {indie_err}")
                self.independent_trader = None
                logger.warning("No primary broker available")
            
            # Initialize position cap enforcer (Maximum 8 positions total across all brokers)
            if self.broker:
                self.enforcer = PositionCapEnforcer(max_positions=8, broker=self.broker)
                
                # Initialize broker failsafes (hard limits and circuit breakers)
                # CRITICAL: Use ONLY master balance, not user balances
                try:
                    from broker_failsafes import create_failsafe_for_broker
                    broker_name = self.broker.broker_type.value if hasattr(self.broker, 'broker_type') else 'coinbase'
                    # Use master_balance only - users are completely independent
                    account_balance = master_balance if master_balance > 0 else 100.0
                    self.failsafes = create_failsafe_for_broker(broker_name, account_balance)
                    logger.info(f"🛡️  Broker failsafes initialized for {broker_name} (Master balance: ${account_balance:,.2f})")
                except Exception as e:
                    logger.warning(f"⚠️  Failed to initialize broker failsafes: {e}")
                    self.failsafes = None
                
                # Initialize market adaptation engine
                try:
                    from market_adaptation import create_market_adapter
                    self.market_adapter = create_market_adapter(learning_enabled=True)
                    logger.info(f"🧠 Market adaptation engine initialized with learning enabled")
                except Exception as e:
                    logger.warning(f"⚠️  Failed to initialize market adaptation: {e}")
                    self.market_adapter = None
                
                # Initialize APEX strategy with primary broker
                self.apex = NIJAApexStrategyV71(broker_client=self.broker)
                
                # Add delay before syncing positions to avoid rate limiting
                time.sleep(0.5)
                
                # CRITICAL: Sync position tracker with actual broker positions at startup
                if hasattr(self.broker, 'position_tracker') and self.broker.position_tracker:
                    try:
                        broker_positions = self.broker.get_positions()
                        removed = self.broker.position_tracker.sync_with_broker(broker_positions)
                        if removed > 0:
                            logger.info(f"🔄 Synced position tracker: removed {removed} orphaned positions")
                    except Exception as sync_err:
                        logger.warning(f"⚠️ Position tracker sync failed: {sync_err}")
                
                logger.info("✅ TradingStrategy initialized (APEX v7.1 + Multi-Broker + 8-Position Cap)")
            else:
                logger.warning("Strategy initialized in monitor mode (no active brokers)")
                self.enforcer = None
                self.apex = None
        
        except ImportError as e:
            logger.error(f"Failed to import strategy modules: {e}")
            logger.error("Falling back to safe monitor mode (no trades)")
            self.broker = None
            self.broker_manager = None
            self.enforcer = None
            self.apex = None
            self.independent_trader = None
    
    def _log_broker_independence_message(self):
        """
        Helper to log that other brokers continue trading independently.
        This is used when a broker fails to initialize to reassure users
        that the failure is isolated and doesn't affect other exchanges.
        """
        logger.info("")
        logger.info("   ✅ OTHER BROKERS CONTINUE TRADING INDEPENDENTLY")
        logger.info("   ℹ️  Kraken offline does NOT block Coinbase or other exchanges")
        logger.info("")
    
    def _register_kraken_for_retry(self, kraken_broker):
        """
        Register a Kraken broker for background retry attempts.
        
        This helper method extracts the dual registration logic to avoid code duplication.
        The broker is registered in multiple places for different purposes:
        - failed_brokers: Tracks error messages for diagnostics/debugging
        - broker_manager: Enables trading loop to monitor and retry
        - multi_account_manager: Consistent account management
        
        This dual registration is intentional - the broker is "failed" for
        diagnostics but "active" for retry attempts, enabling self-healing.
        
        Args:
            kraken_broker: KrakenBroker instance to register
        """
        self.failed_brokers[BrokerType.KRAKEN] = kraken_broker
        self.broker_manager.add_broker(kraken_broker)
        self.multi_account_manager.master_brokers[BrokerType.KRAKEN] = kraken_broker
        logger.info("   ✅ Kraken registered for background connection retry")
    
    def _init_advanced_features(self):
        """Initialize progressive targets, exchange risk profiles, and capital allocation.
        
        This is optional and will gracefully degrade if modules are not available.
        
        Also initializes PRO MODE rotation manager if enabled.
        """
        # Initialize PRO MODE rotation manager
        pro_mode_enabled = os.getenv('PRO_MODE', 'false').lower() in ('true', '1', 'yes')
        min_free_reserve_pct = float(os.getenv('PRO_MODE_MIN_RESERVE_PCT', '0.15'))
        
        if pro_mode_enabled:
            try:
                from rotation_manager import RotationManager
                self.rotation_manager = RotationManager(
                    min_free_balance_pct=min_free_reserve_pct,
                    rotation_enabled=True,
                    min_opportunity_improvement=0.20  # 20% improvement required for rotation
                )
                logger.info("=" * 70)
                logger.info("🔄 PRO MODE ACTIVATED - Position Rotation Enabled")
                logger.info(f"   Min free balance reserve: {min_free_reserve_pct*100:.0f}%")
                logger.info(f"   Position values count as capital")
                logger.info(f"   Can rotate positions for better opportunities")
                logger.info("=" * 70)
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize PRO MODE: {e}")
                logger.info("   Falling back to standard mode")
                self.rotation_manager = None
                pro_mode_enabled = False
        else:
            logger.info("ℹ️ PRO MODE disabled (set PRO_MODE=true to enable)")
            self.rotation_manager = None
        
        self.pro_mode_enabled = pro_mode_enabled
        
        try:
            # Import advanced trading modules
            from advanced_trading_integration import AdvancedTradingManager, ExchangeType
            
            # Get initial capital estimate (will be updated after broker connection)
            # Validate the environment variable before conversion
            initial_capital_str = os.getenv('INITIAL_CAPITAL', '100')
            try:
                initial_capital = float(initial_capital_str)
                if initial_capital <= 0:
                    logger.warning(f"⚠️ Invalid INITIAL_CAPITAL={initial_capital_str}, using default $100")
                    initial_capital = 100.0
            except (ValueError, TypeError):
                logger.warning(f"⚠️ Invalid INITIAL_CAPITAL={initial_capital_str}, using default $100")
                initial_capital = 100.0
            
            allocation_strategy = os.getenv('ALLOCATION_STRATEGY', 'conservative')
            
            # Initialize advanced manager
            self.advanced_manager = AdvancedTradingManager(
                total_capital=initial_capital,
                allocation_strategy=allocation_strategy
            )
            
            logger.info("=" * 70)
            logger.info("✅ Advanced Trading Features Enabled:")
            logger.info(f"   📈 Progressive Targets: ${self.advanced_manager.target_manager.get_current_target():.2f}/day")
            logger.info(f"   🏦 Exchange Profiles: Loaded")
            logger.info(f"   💰 Capital Allocation: {allocation_strategy}")
            logger.info("=" * 70)
            
        except ImportError as e:
            logger.info(f"ℹ️ Advanced trading features not available: {e}")
            logger.info("   Continuing with standard trading mode")
            self.advanced_manager = None
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize advanced features: {e}")
            self.advanced_manager = None
    
    def start_independent_multi_broker_trading(self):
        """
        Start independent trading threads for all connected and funded brokers.
        Each broker operates in complete isolation to prevent cascade failures.
        
        Returns:
            bool: True if independent trading started successfully
        """
        if not self.independent_trader:
            logger.warning("⚠️  Independent trader not initialized")
            return False
        
        if not self.broker_manager or not self.broker_manager.brokers:
            logger.warning("⚠️  No brokers available for independent trading")
            return False
        
        try:
            # Start independent trading threads and check if any were started
            success = self.independent_trader.start_independent_trading()
            return bool(success)
        except Exception as e:
            logger.error(f"❌ Failed to start independent trading: {e}")
            return False
    
    def stop_independent_trading(self):
        """
        Stop all independent trading threads gracefully.
        """
        if self.independent_trader:
            self.independent_trader.stop_all_trading()
        else:
            logger.warning("⚠️  Independent trader not initialized, nothing to stop")
    
    def get_multi_broker_status(self) -> Dict:
        """
        Get status of all brokers and independent trading.
        
        Returns:
            dict: Status summary including broker health and trading activity
        """
        if not self.independent_trader:
            return {
                'error': 'Independent trader not initialized',
                'mode': 'single_broker'
            }
        
        return self.independent_trader.get_status_summary()
    
    def log_multi_broker_status(self):
        """
        Log current status of all brokers.
        """
        if self.independent_trader:
            self.independent_trader.log_status_summary()
        else:
            logger.info("📊 Single broker mode (independent trading not enabled)")
    
    def _get_cached_candles(self, symbol: str, timeframe: str = '5m', count: int = 100, broker=None):
        """
        Get candles with caching to reduce API calls.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candle timeframe
            count: Number of candles
            broker: Optional broker instance to use. If not provided, uses self.broker.
            
        Returns:
            List of candle dicts or empty list
        """
        # Use provided broker or fall back to self.broker
        active_broker = broker if broker is not None else self.broker
        
        cache_key = f"{symbol}_{timeframe}_{count}"
        current_time = time.time()
        
        # Check cache first
        if cache_key in self.candle_cache:
            cached_time, cached_data = self.candle_cache[cache_key]
            if current_time - cached_time < self.CANDLE_CACHE_TTL:
                logger.debug(f"   {symbol}: Using cached candles (age: {int(current_time - cached_time)}s)")
                return cached_data
        
        # Cache miss or expired - fetch fresh data
        candles = active_broker.get_candles(symbol, timeframe, count)
        
        # Cache the result (even if empty, to avoid repeated failed requests)
        self.candle_cache[cache_key] = (current_time, candles)
        
        return candles
    
    def _get_broker_name(self, broker) -> str:
        """
        Get broker name for logging from broker instance.
        
        Args:
            broker: Broker instance (may be None or lack broker_type)
            
        Returns:
            str: Broker name (e.g., 'coinbase', 'kraken') or 'unknown'
        """
        return broker.broker_type.value if broker and hasattr(broker, 'broker_type') else 'unknown'
    
    def _is_broker_eligible_for_entry(self, broker: Optional[object]) -> Tuple[bool, str]:
        """
        Check if a broker is eligible for new entry (BUY) orders.
        
        A broker is eligible if:
        1. It's connected
        2. It's not in EXIT_ONLY mode
        3. Account balance meets minimum threshold
        
        Args:
            broker: Broker instance to check (uses duck typing to avoid circular imports)
            
        Returns:
            tuple: (is_eligible: bool, reason: str)
        """
        if not broker:
            return False, "Broker not available"
        
        if not broker.connected:
            return False, f"{self._get_broker_name(broker).upper()} not connected"
        
        # Check if broker is in EXIT_ONLY mode
        if hasattr(broker, 'exit_only_mode') and broker.exit_only_mode:
            return False, f"{self._get_broker_name(broker).upper()} in EXIT-ONLY mode"
        
        # Check if account balance meets minimum threshold
        try:
            balance = broker.get_account_balance()
            broker_type = broker.broker_type if hasattr(broker, 'broker_type') else None
            min_balance = BROKER_MIN_BALANCE.get(broker_type, MIN_BALANCE_TO_TRADE_USD)
            
            if balance < min_balance:
                return False, f"{self._get_broker_name(broker).upper()} balance ${balance:.2f} < ${min_balance:.2f} minimum"
            
            return True, "Eligible"
        except Exception as e:
            return False, f"{self._get_broker_name(broker).upper()} balance check failed: {e}"
    
    def _select_entry_broker(self, all_brokers: Dict[BrokerType, object]) -> Tuple[Optional[object], Optional[str], Dict[str, str]]:
        """
        Select the best broker for new entry (BUY) orders based on priority.
        
        Checks brokers in ENTRY_BROKER_PRIORITY order and returns the first eligible one.
        Coinbase is automatically deprioritized if balance < $25.
        
        Args:
            all_brokers: Dict of {BrokerType: broker_instance} for all available brokers
            
        Returns:
            tuple: (broker_instance, broker_name, eligibility_reasons) or (None, None, reasons)
        """
        eligibility_status = {}
        
        # Check each broker in priority order
        for broker_type in ENTRY_BROKER_PRIORITY:
            broker = all_brokers.get(broker_type)
            
            if not broker:
                eligibility_status[broker_type.value] = "Not configured"
                continue
            
            is_eligible, reason = self._is_broker_eligible_for_entry(broker)
            eligibility_status[broker_type.value] = reason
            
            if is_eligible:
                broker_name = self._get_broker_name(broker)
                logger.info(f"✅ Selected {broker_name.upper()} for entry (priority: {ENTRY_BROKER_PRIORITY.index(broker_type) + 1})")
                return broker, broker_name, eligibility_status
        
        # No eligible broker found
        return None, None, eligibility_status
    
    def _is_zombie_position(self, pnl_percent: float, entry_time_available: bool, position_age_hours: float) -> bool:
        """
        Detect if a position is a "zombie" - stuck at ~0% P&L for too long.
        
        Zombie positions occur when auto-import masks a losing trade by setting
        entry_price = current_price, causing P&L to reset to 0%. These positions
        never show as losing and can hold indefinitely, tying up capital.
        
        Args:
            pnl_percent: Current P&L percentage
            entry_time_available: Whether position has entry time tracked
            position_age_hours: Hours since position entry
            
        Returns:
            bool: True if position is a zombie (should be exited)
        """
        # Check if P&L is stuck near zero
        pnl_stuck_at_zero = abs(pnl_percent) < ZOMBIE_PNL_THRESHOLD
        
        # Check if position is old enough to be suspicious
        old_enough = entry_time_available and position_age_hours >= ZOMBIE_POSITION_HOURS
        
        # Zombie if both conditions are true
        return pnl_stuck_at_zero and old_enough
    
    def _get_rotated_markets(self, all_markets: list) -> list:
        """
        Get next batch of markets to scan using rotation strategy.
        
        UPDATED (Jan 10, 2026): Added adaptive batch sizing to prevent API rate limiting
        - Starts with small batch (5 markets) on fresh start or after API errors
        - Gradually increases to max batch size (15 markets) over warmup period
        - Reduces batch size when API health score is low
        
        This prevents scanning the same markets every cycle and distributes
        API load across time. With 730 markets and batch size of 5-15,
        we complete a full rotation in multiple hours.
        
        Args:
            all_markets: Full list of available markets
            
        Returns:
            Subset of markets for this cycle
        """
        # Calculate adaptive batch size based on warmup and API health
        if self.cycle_count < MARKET_BATCH_WARMUP_CYCLES:
            # Warmup phase: use minimum batch size
            batch_size = MARKET_BATCH_SIZE_MIN
            logger.info(f"   🔥 Warmup mode: cycle {self.cycle_count + 1}/{MARKET_BATCH_WARMUP_CYCLES}, batch size={batch_size}")
        elif self.api_health_score < 50:
            # API health degraded: reduce batch size
            batch_size = MARKET_BATCH_SIZE_MIN
            logger.warning(f"   ⚠️  API health low ({self.api_health_score}%), using reduced batch size={batch_size}")
        elif self.api_health_score < 80:
            # Moderate health: use mid-range batch size
            batch_size = (MARKET_BATCH_SIZE_MIN + MARKET_BATCH_SIZE_MAX) // 2
            logger.info(f"   📊 API health moderate ({self.api_health_score}%), batch size={batch_size}")
        else:
            # Good health: use maximum batch size
            batch_size = MARKET_BATCH_SIZE_MAX
        
        if not MARKET_ROTATION_ENABLED or len(all_markets) <= batch_size:
            # If rotation disabled or fewer markets than batch size, use all markets
            return all_markets[:batch_size]
        
        # Calculate batch boundaries
        total_markets = len(all_markets)
        start_idx = self.market_rotation_offset
        end_idx = start_idx + batch_size
        
        # Handle wrap-around
        if end_idx <= total_markets:
            batch = all_markets[start_idx:end_idx]
        else:
            # Wrap around to beginning
            batch = all_markets[start_idx:] + all_markets[:end_idx - total_markets]
        
        # Update offset for next cycle
        self.market_rotation_offset = end_idx % total_markets
        
        # Log rotation progress
        rotation_pct = (self.market_rotation_offset / total_markets) * 100
        logger.info(f"   📊 Market rotation: scanning batch {start_idx}-{min(end_idx, total_markets)} of {total_markets} ({rotation_pct:.0f}% through cycle)")
        
        return batch

    def _get_stop_loss_tier(self, broker, account_balance: float) -> tuple:
        """
        Determine the appropriate stop-loss tier based on broker type and account balance.
        
        Returns 3-tier stop-loss system:
        - Tier 1: Primary trading stop (for risk management)
        - Tier 2: Emergency micro-stop (for logic failure prevention)
        - Tier 3: Catastrophic failsafe (last resort)
        
        Args:
            broker: Broker instance (to determine broker type)
            account_balance: Current account balance in USD
            
        Returns:
            tuple: (primary_stop, micro_stop, catastrophic_stop, description)
        """
        # Determine broker type with multiple fallback approaches
        # This flexibility handles various broker implementations without requiring
        # strict interface contracts. While not ideal, it provides robustness across
        # different broker adapter patterns (BrokerInterface, direct API wrappers, etc.)
        broker_name = 'coinbase'  # default
        if hasattr(broker, 'broker_type'):
            broker_name = broker.broker_type.value.lower() if hasattr(broker.broker_type, 'value') else str(broker.broker_type).lower()
        elif hasattr(broker, '__class__'):
            broker_name = broker.__class__.__name__.lower()
        
        # Kraken with small balance: Use -0.6% to -0.8% primary stop
        if 'kraken' in broker_name and account_balance < 100:
            # For small Kraken balances, use conservative -0.8% primary stop
            # This accounts for spread (0.1%) + fees (0.36%) + slippage (0.1%) + buffer (0.24%)
            primary_stop = STOP_LOSS_PRIMARY_KRAKEN  # -0.8%
            description = f"Kraken small balance (${account_balance:.2f}): Primary -0.8%, Micro -1.0%, Failsafe -5.0%"
        
        # Kraken with larger balance: Can use tighter stop
        elif 'kraken' in broker_name:
            # For larger Kraken balances, use -0.6% minimum (tighter)
            primary_stop = STOP_LOSS_PRIMARY_KRAKEN_MIN  # -0.6%
            description = f"Kraken (${account_balance:.2f}): Primary -0.6%, Micro -1.0%, Failsafe -5.0%"
        
        # Coinbase or other exchanges: Use -1.0% primary stop (higher fees)
        else:
            # Higher fees require wider stop-loss
            primary_stop = -0.010  # -1.0% for Coinbase/other
            description = f"{broker_name.upper()} (${account_balance:.2f}): Primary -1.0%, Micro -1.0%, Failsafe -5.0%"
        
        return (
            primary_stop,           # Tier 1: Primary trading stop
            STOP_LOSS_MICRO,        # Tier 2: Emergency micro-stop (-1%)
            STOP_LOSS_EMERGENCY,    # Tier 3: Catastrophic failsafe (-5%)
            description
        )

    def run_cycle(self, broker=None, user_mode=False):
        """Execute a complete trading cycle with position cap enforcement.
        
        Args:
            broker: Optional broker instance to use for this cycle. If not provided,
                   uses self.broker (default behavior for backward compatibility).
                   This parameter enables thread-safe multi-broker trading by avoiding
                   shared state mutation - each thread passes its own broker instance
                   instead of modifying the shared self.broker variable.
            user_mode: If True, runs in USER mode which:
                      - DISABLES strategy execution (no signal generation)
                      - ONLY manages existing positions (exits, stops, targets)
                      - Users receive signals via CopyTradeEngine, not from strategy
                      Default False for MASTER accounts (full strategy execution)
        
        Steps:
        1. Enforce position cap (auto-sell excess if needed)
        2. [MASTER ONLY] Scan markets for opportunities
        3. [MASTER ONLY] Execute entry logic / [USER] Execute position exits only
        4. Update trailing stops and take profits
        5. Log cycle summary
        """
        # Use provided broker or fall back to self.broker (thread-safe approach)
        active_broker = broker if broker is not None else self.broker
        
        # Log mode for clarity
        mode_label = "USER (position management only)" if user_mode else "MASTER (full strategy)"
        logger.info(f"🔄 Trading cycle mode: {mode_label}")
        try:
            # 🚨 EMERGENCY: Check if LIQUIDATE_ALL mode is active
            liquidate_all_file = os.path.join(os.path.dirname(__file__), '..', 'LIQUIDATE_ALL_NOW.conf')
            if os.path.exists(liquidate_all_file):
                logger.error("🚨 EMERGENCY LIQUIDATION MODE ACTIVE")
                logger.error("   SELLING ALL POSITIONS IMMEDIATELY")
                
                sold_count = 0
                total_positions = 0
                
                try:
                    if active_broker:
                        try:
                            positions = call_with_timeout(active_broker.get_positions, timeout_seconds=30)
                            if positions[1]:  # Error occurred
                                logger.error(f"   Failed to get positions: {positions[1]}")
                                positions = []
                            else:
                                positions = positions[0] or []
                        except Exception as e:
                            logger.error(f"   Exception getting positions: {e}")
                            positions = []
                        
                        total_positions = len(positions)
                        logger.error(f"   Found {total_positions} positions to liquidate")
                        
                        for i, pos in enumerate(positions, 1):
                            try:
                                symbol = pos.get('symbol', 'UNKNOWN')
                                currency = pos.get('currency', symbol.split('-')[0])
                                quantity = pos.get('quantity', 0)
                                
                                if quantity <= 0:
                                    logger.error(f"   [{i}/{total_positions}] SKIPPING {currency} (quantity={quantity})")
                                    continue
                                
                                logger.error(f"   [{i}/{total_positions}] FORCE SELLING {quantity:.8f} {currency}...")
                                
                                try:
                                    result = call_with_timeout(
                                        active_broker.place_market_order,
                                        args=(symbol, 'sell', quantity),
                                        kwargs={'size_type': 'base'},
                                        timeout_seconds=30
                                    )
                                    if result[1]:  # Error from call_with_timeout
                                        logger.error(f"   ❌ Timeout/error selling {currency}: {result[1]}")
                                    else:
                                        result_dict = result[0] or {}
                                        if result_dict and result_dict.get('status') not in ['error', 'unfilled']:
                                            logger.error(f"   ✅ SOLD {currency}")
                                            sold_count += 1
                                        else:
                                            error_msg = result_dict.get('error', result_dict.get('message', 'Unknown'))
                                            logger.error(f"   ❌ Failed to sell {currency}: {error_msg}")
                                except Exception as e:
                                    logger.error(f"   ❌ Exception during sell: {e}")
                                
                                # Throttle to avoid Coinbase 429 rate limits
                                try:
                                    time.sleep(1.0)
                                except Exception:
                                    pass
                            
                            except Exception as pos_err:
                                logger.error(f"   ❌ Position processing error: {pos_err}")
                                continue
                        
                        logger.error(f"   Liquidation round complete: {sold_count}/{total_positions} sold")
                
                except Exception as liquidation_error:
                    logger.error(f"   ❌ Emergency liquidation critical error: {liquidation_error}")
                    import traceback
                    logger.error(traceback.format_exc())
                
                finally:
                    # GUARANTEED cleanup - always remove the trigger file
                    try:
                        if os.path.exists(liquidate_all_file):
                            os.remove(liquidate_all_file)
                            logger.error("✅ Emergency liquidation cycle complete - removed LIQUIDATE_ALL_NOW.conf")
                    except Exception as cleanup_err:
                        logger.error(f"   Warning: Could not delete trigger file: {cleanup_err}")
                
                return  # Skip normal trading cycle
            
            # CRITICAL: Enforce position cap first
            if self.enforcer:
                logger.info(f"🔍 Enforcing position cap (max {MAX_POSITIONS_ALLOWED})...")
                success, result = self.enforcer.enforce_cap()
                if result['excess'] > 0:
                    logger.warning(f"⚠️ Excess positions detected: {result['excess']} over cap")
                    logger.info(f"   Sold {result['sold']} positions")
            
            # CRITICAL: Check if new entries are blocked
            current_positions = active_broker.get_positions() if active_broker else []
            stop_entries_file = os.path.join(os.path.dirname(__file__), '..', 'STOP_ALL_ENTRIES.conf')
            entries_blocked = os.path.exists(stop_entries_file)
            
            if entries_blocked:
                logger.error("🛑 ALL NEW ENTRIES BLOCKED: STOP_ALL_ENTRIES.conf is active")
                logger.info("   Exiting positions only (no new buys)")
            elif len(current_positions) >= MAX_POSITIONS_ALLOWED:
                logger.warning(f"🛑 ENTRY BLOCKED: Position cap reached ({len(current_positions)}/{MAX_POSITIONS_ALLOWED})")
                logger.info("   Closing positions only until below cap")
            else:
                logger.info(f"✅ Position cap OK ({len(current_positions)}/{MAX_POSITIONS_ALLOWED}) - entries enabled")
            
            # Get account balance for position sizing
            if not active_broker or not self.apex:
                logger.info("📡 Monitor mode (strategy not loaded; no trades)")
                return
            
            # FIX #1: Update portfolio state from broker data
            # Get detailed balance including crypto holdings
            # PRO MODE: Also calculate total capital (free balance + position values)
            if hasattr(active_broker, 'get_account_balance_detailed'):
                balance_data = active_broker.get_account_balance_detailed()
            else:
                balance_data = {'trading_balance': active_broker.get_account_balance()}
            account_balance = balance_data.get('trading_balance', 0.0)
            
            # Update portfolio state (if available)
            if self.portfolio_manager and hasattr(self, 'master_portfolio') and self.master_portfolio:
                try:
                    # Update portfolio from current broker state
                    self.portfolio_manager.update_portfolio_from_broker(
                        portfolio=self.master_portfolio,
                        available_cash=account_balance,
                        positions=current_positions
                    )
                    
                    # Log portfolio summary
                    summary = self.master_portfolio.get_summary()
                    logger.info(f"📊 Portfolio State (Total Equity Accounting):")
                    logger.info(f"   Available Cash: ${summary['available_cash']:.2f}")
                    logger.info(f"   Position Value: ${summary['total_position_value']:.2f}")
                    logger.info(f"   Unrealized P&L: ${summary['unrealized_pnl']:.2f}")
                    logger.info(f"   TOTAL EQUITY: ${summary['total_equity']:.2f}")
                    logger.info(f"   Positions: {summary['position_count']}")
                    logger.info(f"   Cash Utilization: {summary['cash_utilization_pct']:.1f}%")
                except Exception as e:
                    logger.warning(f"⚠️ Could not update portfolio state: {e}")
            
            # ENHANCED FUND VISIBILITY (Jan 19, 2026)
            # Always track held funds and total capital - not just in PRO_MODE
            # This prevents "bleeding" confusion where funds in trades appear missing
            held_funds = balance_data.get('total_held', 0.0)
            total_funds = balance_data.get('total_funds', account_balance)
            
            # ALWAYS calculate position values (not just in PRO_MODE)
            # Users need to see funds in active trades regardless of mode
            position_value = 0.0
            position_count = 0
            total_capital = account_balance
            
            if hasattr(active_broker, 'get_total_capital'):
                try:
                    capital_data = active_broker.get_total_capital(include_positions=True)
                    position_value = capital_data.get('position_value', 0.0)
                    position_count = capital_data.get('position_count', 0)
                    total_capital = capital_data.get('total_capital', account_balance)
                except Exception as e:
                    logger.warning(f"⚠️ Could not calculate position values: {e}")
                    position_value = 0.0
                    position_count = 0
                    total_capital = account_balance
            
            # Log comprehensive balance breakdown showing ALL fund allocations
            logger.info(f"💰 Account Balance Breakdown:")
            logger.info(f"   ✅ Available (free to trade): ${account_balance:.2f}")
            
            if held_funds > 0:
                logger.info(f"   🔒 Held (in open orders): ${held_funds:.2f}")
            
            if position_value > 0:
                logger.info(f"   📊 In Active Positions: ${position_value:.2f} ({position_count} positions)")
            
            # Calculate grand total including held funds and position values
            grand_total = account_balance + held_funds + position_value
            logger.info(f"   💎 TOTAL ACCOUNT VALUE: ${grand_total:.2f}")
            
            if position_value > 0 or held_funds > 0:
                if grand_total > 0:
                    allocation_pct = (account_balance / grand_total * 100)
                    deployed_pct = 100 - allocation_pct
                    logger.info(f"   📈 Cash allocation: {allocation_pct:.1f}% available, {deployed_pct:.1f}% deployed")
                else:
                    logger.info(f"   📈 Cash allocation: 0.0% available, 0.0% deployed")
            
            # Small delay after balance check to avoid rapid-fire API calls
            time.sleep(0.5)
            
            # STEP 1: Manage existing positions (check for exits/profit taking)
            logger.info(f"📊 Managing {len(current_positions)} open position(s)...")
            
            # Get 3-tier stop-loss configuration for this broker and balance
            primary_stop, micro_stop, catastrophic_stop, stop_description = self._get_stop_loss_tier(active_broker, account_balance)
            logger.info(f"🛡️  Stop-loss tiers: {stop_description}")
            
            # CRITICAL: If over position cap, prioritize selling weakest positions immediately
            # This ensures we get back under cap quickly to avoid further bleeding
            # Position cap set to 8 maximum concurrent positions
            positions_over_cap = len(current_positions) - MAX_POSITIONS_ALLOWED
            if positions_over_cap > 0:
                logger.warning(f"🚨 OVER POSITION CAP: {len(current_positions)}/{MAX_POSITIONS_ALLOWED} positions ({positions_over_cap} excess)")
                logger.warning(f"   Will prioritize selling {positions_over_cap} weakest positions first")
            
            # CRITICAL FIX: Identify ALL positions that need to exit first
            # Then sell them ALL concurrently, not one at a time
            positions_to_exit = []
            
            for position_idx, position in enumerate(current_positions):
                try:
                    symbol = position.get('symbol')
                    if not symbol:
                        continue
                    
                    # Skip positions we know can't be sold (too small/dust)
                    # But allow retry after timeout in case position grew or API error was temporary
                    if symbol in self.unsellable_positions:
                        # Check if enough time has passed to retry
                        marked_time = self.unsellable_positions[symbol]
                        time_since_marked = time.time() - marked_time
                        if time_since_marked < self.unsellable_retry_timeout:
                            logger.debug(f"   ⏭️ Skipping {symbol} (marked unsellable {time_since_marked/3600:.1f}h ago, retry in {(self.unsellable_retry_timeout - time_since_marked)/3600:.1f}h)")
                            continue
                        else:
                            logger.info(f"   🔄 Retrying {symbol} (marked unsellable {time_since_marked/3600:.1f}h ago - timeout reached)")
                            # Remove from unsellable dict to allow full processing
                            del self.unsellable_positions[symbol]
                    
                    logger.info(f"   Analyzing {symbol}...")
                    
                    # Get current price
                    current_price = active_broker.get_current_price(symbol)
                    if not current_price or current_price == 0:
                        logger.warning(f"   ⚠️ Could not get price for {symbol}")
                        continue
                    
                    # Get position value
                    quantity = position.get('quantity', 0)
                    position_value = current_price * quantity
                    
                    logger.info(f"   {symbol}: {quantity:.8f} @ ${current_price:.2f} = ${position_value:.2f}")
                    
                    # PROFITABILITY MODE: Aggressive exit on weak markets
                    # Exit positions when market conditions deteriorate to prevent bleeding
                    
                    # CRITICAL FIX: We don't have entry_price from Coinbase API!
                    # Instead, use aggressive exit criteria based on:
                    # 1. Market conditions (if filter fails, exit immediately)
                    # 2. Small position size (anything under $1 should be exited)
                    # 3. RSI overbought/oversold (take profits or cut losses)
                    
                    # AUTO-EXIT small positions (under $1) - these are likely losers
                    if position_value < MIN_POSITION_VALUE:
                        logger.info(f"   🔴 SMALL POSITION AUTO-EXIT: {symbol} (${position_value:.2f} < ${MIN_POSITION_VALUE})")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': f'Small position cleanup (${position_value:.2f})'
                        })
                        continue
                    
                    # PROFIT-BASED EXIT LOGIC (NEW!)
                    # Check if we have entry price tracked for this position
                    entry_price_available = False
                    entry_time_available = False
                    position_age_hours = 0
                    just_auto_imported = False  # Track if position was just imported this cycle
                    
                    if active_broker and hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                        try:
                            tracked_position = active_broker.position_tracker.get_position(symbol)
                            if tracked_position:
                                entry_price_available = True
                                
                                # Calculate position age (needed for both stop-loss and time-based logic)
                                entry_time = tracked_position.get('first_entry_time')
                                if entry_time:
                                    try:
                                        entry_dt = datetime.fromisoformat(entry_time)
                                        now = datetime.now()
                                        position_age_hours = (now - entry_dt).total_seconds() / 3600
                                        entry_time_available = True
                                    except Exception as time_err:
                                        logger.debug(f"   Could not parse entry time for {symbol}: {time_err}")
                            
                            # CRITICAL FIX (Jan 19, 2026): Calculate P&L FIRST, check stop-loss BEFORE time-based exits
                            # Railway Golden Rule #5: Stop-loss > time exit (always)
                            # The old logic had time-based exits BEFORE stop-loss checks, which is backwards!
                            pnl_data = active_broker.position_tracker.calculate_pnl(symbol, current_price)
                            if pnl_data:
                                entry_price_available = True
                                pnl_percent = pnl_data['pnl_percent']
                                pnl_dollars = pnl_data['pnl_dollars']
                                entry_price = pnl_data['entry_price']
                                
                                # CRITICAL: Validate PnL is in fractional format (not percentage)
                                # If abs(pnl_percent) >= 1, it's likely using wrong scale (percentage instead of fractional)
                                assert abs(pnl_percent) < 1.0, f"PNL scale mismatch for {symbol}: {pnl_percent} (expected fractional format like -0.01 for -1%)"
                                
                                logger.info(f"   💰 P&L: ${pnl_dollars:+.2f} ({pnl_percent*100:+.2f}%) | Entry: ${entry_price:.2f}")
                                
                                # 🛡️ 3-TIER PROTECTIVE STOP-LOSS SYSTEM (JAN 21, 2026)
                                # Tier 1: Primary trading stop (varies by broker and balance)
                                # Tier 2: Emergency micro-stop to prevent logic failures
                                # Tier 3: Catastrophic failsafe (last resort)
                                
                                # TIER 1: PRIMARY TRADING STOP-LOSS
                                # This is the REAL stop-loss for risk management
                                # For Kraken small balances: -0.6% to -0.8%
                                # For Coinbase/other: -1.0%
                                if pnl_percent <= primary_stop:
                                    logger.warning(f"   🛡️ PRIMARY PROTECTIVE STOP-LOSS HIT: {symbol} at {pnl_percent*100:.2f}% (threshold: {primary_stop*100:.2f}%)")
                                    logger.warning(f"   💥 TIER 1: Protective trading stop triggered - capital preservation mode")
                                    
                                    # FIX #2: Use protective stop-loss executor (risk management override)
                                    if self.forced_stop_loss:
                                        success, result, error = self.forced_stop_loss.force_sell_position(
                                            symbol=symbol,
                                            quantity=quantity,
                                            reason=f"Primary protective stop-loss: {pnl_percent*100:.2f}% <= {primary_stop*100:.2f}%"
                                        )
                                        
                                        if success:
                                            logger.info(f"   ✅ PROTECTIVE STOP-LOSS EXECUTED: {symbol}")
                                            # Track the exit
                                            if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                active_broker.position_tracker.track_exit(symbol, quantity)
                                        else:
                                            logger.error(f"   ❌ PROTECTIVE STOP-LOSS FAILED: {error}")
                                    else:
                                        # Fallback to legacy stop-loss if protective executor not available
                                        logger.warning("   ⚠️ Protective stop-loss executor not available, using legacy method")
                                        try:
                                            result = active_broker.place_market_order(
                                                symbol=symbol,
                                                side='sell',
                                                quantity=quantity,
                                                size_type='base'
                                            )
                                            
                                            if result and result.get('status') not in ['error', 'unfilled']:
                                                order_id = result.get('order_id', 'N/A')
                                                logger.info(f"   ✅ ORDER ACCEPTED: Order ID {order_id}")
                                                if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                    active_broker.position_tracker.track_exit(symbol, quantity)
                                            else:
                                                error_msg = result.get('error', 'Unknown error') if result else 'No response'
                                                logger.error(f"   ❌ ORDER REJECTED: {error_msg}")
                                        except Exception as sell_err:
                                            logger.error(f"   ❌ ORDER EXCEPTION: {sell_err}")
                                    
                                    # Skip ALL remaining logic for this position
                                    continue
                                
                                # TIER 2: EMERGENCY MICRO-STOP (Logic failure prevention)
                                # This is NOT a trading stop - it's a failsafe to prevent logic failures
                                # Examples: imported positions, calculation errors, data corruption
                                # Note: This should RARELY trigger - Tier 1 should catch most losses
                                # Only triggers for losses that somehow bypassed Tier 1
                                # (e.g., imported positions without proper entry price tracking)
                                if pnl_percent <= micro_stop:
                                    logger.warning(f"   ⚠️ EMERGENCY MICRO-STOP: {symbol} at {pnl_percent:.2f}% (threshold: {micro_stop*100:.2f}%)")
                                    logger.warning(f"   💥 TIER 2: Emergency micro-stop to prevent logic failures (not a trading stop)")
                                    logger.warning(f"   ⚠️  NOTE: Tier 1 was bypassed - possible imported position or logic error")
                                    
                                    # FIX #2: Use forced stop-loss for emergency too
                                    if self.forced_stop_loss:
                                        success, result, error = self.forced_stop_loss.force_sell_position(
                                            symbol=symbol,
                                            quantity=quantity,
                                            reason=f"Emergency micro-stop: {pnl_percent:.2f}% <= {micro_stop*100:.2f}%"
                                        )
                                        
                                        if success:
                                            logger.info(f"   ✅ EMERGENCY STOP EXECUTED: {symbol}")
                                            if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                active_broker.position_tracker.track_exit(symbol, quantity)
                                        else:
                                            logger.error(f"   ❌ EMERGENCY STOP FAILED: {error}")
                                    else:
                                        # Fallback
                                        try:
                                            result = active_broker.place_market_order(
                                                symbol=symbol,
                                                side='sell',
                                                quantity=quantity,
                                                size_type='base'
                                            )
                                            
                                            if result and result.get('status') not in ['error', 'unfilled']:
                                                order_id = result.get('order_id', 'N/A')
                                                logger.info(f"   ✅ MICRO-STOP EXECUTED: Order ID {order_id}")
                                                if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                    active_broker.position_tracker.track_exit(symbol, quantity)
                                            else:
                                                error_msg = result.get('error', 'Unknown error') if result else 'No response'
                                                logger.error(f"   ❌ MICRO-STOP FAILED: {error_msg}")
                                        except Exception as sell_err:
                                            logger.error(f"   ❌ MICRO-STOP EXCEPTION: {sell_err}")
                                    
                                    continue
                                
                                # ✅ LOSING TRADES: 15-MINUTE MAXIMUM HOLD TIME
                                # For tracked positions with P&L < 0%, enforce STRICT 15-minute max hold time
                                # This prevents capital erosion from positions held too long in a losing state
                                # CRITICAL FIX (Jan 21, 2026): Also exit losing positions WITHOUT entry time tracking
                                # to prevent positions from being stuck indefinitely
                                if pnl_percent < 0:
                                    # Convert position age from hours to minutes
                                    position_age_minutes = position_age_hours * MINUTES_PER_HOUR
                                    
                                    # SCENARIO 1: Position with time tracking that exceeds max hold time
                                    if entry_time_available and position_age_minutes >= MAX_LOSING_POSITION_HOLD_MINUTES:
                                        logger.warning(f"   🚨 LOSING TRADE TIME EXIT: {symbol} at {pnl_percent*100:.2f}% held for {position_age_minutes:.1f} minutes (max: {MAX_LOSING_POSITION_HOLD_MINUTES} min)")
                                        logger.warning(f"   💥 NIJA IS FOR PROFIT, NOT LOSSES - selling immediately!")
                                        positions_to_exit.append({
                                            'symbol': symbol,
                                            'quantity': quantity,
                                            'reason': f'Losing trade time exit (held {position_age_minutes:.1f}min at {pnl_percent*100:.2f}%)'
                                        })
                                        continue
                                    elif not entry_time_available:
                                        # SCENARIO 2: Losing position without time tracking (SAFETY FALLBACK)
                                        # Exit immediately to prevent indefinite losses when we cannot determine age
                                        logger.warning(f"   🚨 LOSING POSITION WITHOUT TIME TRACKING: {symbol} at {pnl_percent*100:.2f}%")
                                        logger.warning(f"   💥 Cannot determine age - exiting to prevent indefinite losses!")
                                        positions_to_exit.append({
                                            'symbol': symbol,
                                            'quantity': quantity,
                                            'reason': f'Losing position without time tracking (P&L: {pnl_percent*100:.2f}%)'
                                        })
                                        continue
                                
                                # TIER 3: CATASTROPHIC PROTECTIVE FAILSAFE (Last resort protection)
                                # This should NEVER be reached in normal operation
                                # Only triggers at -5.0% to catch extreme edge cases
                                if pnl_percent <= catastrophic_stop:
                                    logger.warning(f"   🚨 CATASTROPHIC PROTECTIVE FAILSAFE TRIGGERED: {symbol} at {pnl_percent*100:.2f}% (threshold: {catastrophic_stop*100:.1f}%)")
                                    logger.warning(f"   💥 TIER 3: Last resort capital preservation - severe loss detected!")
                                    logger.warning(f"   🛡️ PROTECTIVE EXIT MODE — Risk Management Override Active")
                                    
                                    # Use forced exit path with retry - bypasses ALL filters
                                    exit_success = False
                                    try:
                                        # Attempt 1: Direct market sell
                                        result = active_broker.place_market_order(
                                            symbol=symbol,
                                            side='sell',
                                            quantity=quantity,
                                            size_type='base'
                                        )
                                        
                                        # Enhanced logging for catastrophic events
                                        if result and result.get('status') not in ['error', 'unfilled']:
                                            order_id = result.get('order_id', 'N/A')
                                            logger.error(f"   ✅ CATASTROPHIC EXIT COMPLETE: Order ID {order_id}")
                                            exit_success = True
                                            if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                active_broker.position_tracker.track_exit(symbol, quantity)
                                        else:
                                            error_msg = result.get('error', 'Unknown error') if result else 'No response'
                                            logger.error(f"   ❌ CATASTROPHIC EXIT ATTEMPT 1 FAILED: {error_msg}")
                                            
                                            # Retry once for catastrophic exits
                                            logger.error(f"   🔄 Retrying catastrophic exit (attempt 2/2)...")
                                            time.sleep(1)  # Brief pause
                                            
                                            result = active_broker.place_market_order(
                                                symbol=symbol,
                                                side='sell',
                                                quantity=quantity,
                                                size_type='base'
                                            )
                                            if result and result.get('status') not in ['error', 'unfilled']:
                                                order_id = result.get('order_id', 'N/A')
                                                logger.error(f"   ✅ CATASTROPHIC EXIT COMPLETE (retry): Order ID {order_id}")
                                                exit_success = True
                                                if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                    active_broker.position_tracker.track_exit(symbol, quantity)
                                            else:
                                                error_msg = result.get('error', 'Unknown error') if result else 'No response'
                                                logger.error(f"   ❌ CATASTROPHIC EXIT RETRY FAILED: {error_msg}")
                                    except Exception as emergency_err:
                                        logger.error(f"   ❌ CATASTROPHIC EXIT EXCEPTION: {symbol} - {emergency_err}")
                                        logger.error(f"   Exception type: {type(emergency_err).__name__}")
                                    
                                    # Log final status
                                    if not exit_success:
                                        logger.error(f"   🛑 CATASTROPHIC EXIT FAILED AFTER 2 ATTEMPTS")
                                        logger.error(f"   🛑 MANUAL INTERVENTION REQUIRED FOR {symbol}")
                                        logger.error(f"   🛑 Position may still be open - check broker manually")
                                    
                                    # Skip to next position - catastrophic exit overrides all other logic
                                    continue
                                
                                # STEPPED PROFIT TAKING - Exit portions at profit targets
                                # This locks in gains and frees capital for new opportunities
                                # Check targets from highest to lowest
                                # FIX #3: Only exit if profit > minimum threshold (spread + fees + buffer)
                                # ENHANCEMENT (Jan 19, 2026): Use broker-specific profit targets
                                # Different brokers have different fee structures
                                # Safely get broker_type, defaulting to generic targets if not available
                                try:
                                    broker_type = getattr(active_broker, 'broker_type', None)
                                except AttributeError:
                                    broker_type = None
                                
                                if broker_type == BrokerType.KRAKEN:
                                    profit_targets = PROFIT_TARGETS_KRAKEN
                                    min_threshold = 0.005  # 0.5% minimum for Kraken (0.36% fees)
                                elif broker_type == BrokerType.COINBASE:
                                    profit_targets = PROFIT_TARGETS_COINBASE
                                    min_threshold = MIN_PROFIT_THRESHOLD  # 1.6% minimum for Coinbase (1.4% fees)
                                else:
                                    # Default to Coinbase targets for unknown brokers (conservative)
                                    profit_targets = PROFIT_TARGETS
                                    min_threshold = MIN_PROFIT_THRESHOLD
                                
                                for target_pct, reason in profit_targets:
                                    if pnl_percent >= target_pct:
                                        # Double-check: ensure profit meets minimum threshold
                                        if pnl_percent >= min_threshold:
                                            logger.info(f"   🎯 PROFIT TARGET HIT: {symbol} at +{pnl_percent:.2f}% (target: +{target_pct}%, min threshold: +{min_threshold*100:.1f}%)")
                                            positions_to_exit.append({
                                                'symbol': symbol,
                                                'quantity': quantity,
                                                'reason': f'{reason} hit (actual: +{pnl_percent:.2f}%)'
                                            })
                                            break  # Exit the for loop, continue to next position
                                        else:
                                            logger.info(f"   ⚠️ Target {target_pct}% hit but profit {pnl_percent:.2f}% < minimum threshold {min_threshold*100:.1f}% - holding")
                                else:
                                    # No profit target hit, check stop loss (LEGACY FALLBACK)
                                    # CRITICAL FIX (Jan 19, 2026): Stop-loss checks happen BEFORE time-based exits
                                    # This ensures losing trades get stopped out immediately, not held for hours
                                    
                                    # CATASTROPHIC STOP LOSS: Force exit at -5% or worse (ABSOLUTE FAILSAFE)
                                    if pnl_percent <= STOP_LOSS_EMERGENCY:
                                        logger.warning(f"   🛡️ CATASTROPHIC PROTECTIVE EXIT: {symbol} at {pnl_percent*100:.2f}% (threshold: {STOP_LOSS_EMERGENCY*100:.0f}%)")
                                        logger.warning(f"   💥 PROTECTIVE ACTION: Exiting to prevent severe capital loss")
                                        positions_to_exit.append({
                                            'symbol': symbol,
                                            'quantity': quantity,
                                            'reason': f'Catastrophic protective exit at {STOP_LOSS_EMERGENCY*100:.0f}% (actual: {pnl_percent*100:.2f}%)'
                                        })
                                    # STANDARD STOP LOSS: Normal stop-loss threshold
                                    # WITH MINIMUM LOSS FLOOR: Only trigger if loss is significant enough
                                    elif pnl_percent <= STOP_LOSS_THRESHOLD and pnl_percent <= MIN_LOSS_FLOOR:
                                        logger.warning(f"   🛑 PROTECTIVE STOP-LOSS HIT: {symbol} at {pnl_percent*100:.2f}% (threshold: {STOP_LOSS_THRESHOLD*100:.2f}%)")
                                        positions_to_exit.append({
                                            'symbol': symbol,
                                            'quantity': quantity,
                                            'reason': f'Protective stop-loss at {STOP_LOSS_THRESHOLD*100:.2f}% (actual: {pnl_percent*100:.2f}%)'
                                        })
                                    # WARNING THRESHOLD: Approaching stop loss
                                    elif pnl_percent <= STOP_LOSS_WARNING:
                                        logger.warning(f"   ⚠️ Approaching protective stop: {symbol} at {pnl_percent*100:.2f}%")
                                        # Don't exit yet, but log it
                                    elif self._is_zombie_position(pnl_percent, entry_time_available, position_age_hours):
                                        # ZOMBIE POSITION DETECTION: Position stuck at ~0% P&L for too long
                                        # This catches auto-imported positions that mask actual losses
                                        logger.warning(f"   🧟 ZOMBIE POSITION DETECTED: {symbol} at {pnl_percent:+.2f}% after {position_age_hours:.1f}h | "
                                                      f"Position stuck at ~0% P&L suggests auto-import masked a losing trade | "
                                                      f"AGGRESSIVE EXIT to prevent indefinite holding of potential loser")
                                        positions_to_exit.append({
                                            'symbol': symbol,
                                            'quantity': quantity,
                                            'reason': f'Zombie position exit (stuck at {pnl_percent:+.2f}% for {position_age_hours:.1f}h - likely masked loser)'
                                        })
                                    else:
                                        # Position has entry price but not at any exit threshold
                                        # CRITICAL FIX (Jan 19, 2026): Add time-based exits AFTER stop-loss checks
                                        # Railway Golden Rule #5: Stop-loss > time exit (always)
                                        # Only check time-based exits if stop-loss didn't trigger
                                        
                                        # Common holding message (avoid duplication)
                                        holding_msg = f"   📊 Holding {symbol}: P&L {pnl_percent:+.2f}% (no exit threshold reached)"
                                        
                                        if entry_time_available:
                                            # EMERGENCY TIME-BASED EXIT: Force exit ALL positions after 12 hours (FAILSAFE)
                                            # This is a last-resort failsafe for profitable positions that aren't hitting targets
                                            if position_age_hours >= MAX_POSITION_HOLD_EMERGENCY:
                                                logger.error(f"   🚨 EMERGENCY TIME EXIT: {symbol} held for {position_age_hours:.1f} hours (emergency max: {MAX_POSITION_HOLD_EMERGENCY})")
                                                logger.error(f"   💥 FORCE SELLING to prevent indefinite holding!")
                                                positions_to_exit.append({
                                                    'symbol': symbol,
                                                    'quantity': quantity,
                                                    'reason': f'EMERGENCY time exit (held {position_age_hours:.1f}h, max {MAX_POSITION_HOLD_EMERGENCY}h)'
                                                })
                                            # TIME-BASED EXIT: Auto-exit stale positions
                                            elif position_age_hours >= MAX_POSITION_HOLD_HOURS:
                                                logger.warning(f"   ⏰ STALE POSITION EXIT: {symbol} held for {position_age_hours:.1f} hours (max: {MAX_POSITION_HOLD_HOURS})")
                                                positions_to_exit.append({
                                                    'symbol': symbol,
                                                    'quantity': quantity,
                                                    'reason': f'Time-based exit (held {position_age_hours:.1f}h, max {MAX_POSITION_HOLD_HOURS}h)'
                                                })
                                            elif position_age_hours >= STALE_POSITION_WARNING_HOURS:
                                                logger.info(f"   ⚠️ Position aging: {symbol} held for {position_age_hours:.1f} hours")
                                                logger.info(holding_msg)
                                            else:
                                                logger.info(holding_msg)
                                        else:
                                            logger.info(holding_msg)
                                    continue  # Continue to next position check
                                
                                # If we got here via break, skip remaining checks
                                continue
                                
                        except Exception as pnl_err:
                            logger.debug(f"   Could not calculate P&L for {symbol}: {pnl_err}")
                    
                    # Log if no entry price available - this helps debug why positions aren't taking profit
                    if not entry_price_available:
                        logger.warning(f"   ⚠️ No entry price tracked for {symbol} - attempting auto-import")
                        
                        # ✅ FIX 1: AUTO-IMPORTED POSITION EXIT SUPPRESSION FIX
                        # Auto-import orphaned positions with aggressive exit parameters
                        # These positions are likely losers and should be exited aggressively
                        auto_import_success = False
                        real_entry_price = None
                        
                        # Try to get real entry price from broker API
                        if active_broker and hasattr(active_broker, 'get_real_entry_price'):
                            try:
                                real_entry_price = active_broker.get_real_entry_price(symbol)
                                if real_entry_price and real_entry_price > 0:
                                    logger.info(f"   ✅ Real entry price fetched: ${real_entry_price:.2f}")
                            except Exception as fetch_err:
                                logger.debug(f"   Could not fetch real entry price: {fetch_err}")
                        
                        # If real entry cannot be fetched, use safety default
                        if not real_entry_price or real_entry_price <= 0:
                            # SAFETY DEFAULT: Assume entry was higher than current by multiplier
                            # This creates immediate negative P&L to trigger aggressive exits
                            real_entry_price = current_price * SAFETY_DEFAULT_ENTRY_MULTIPLIER
                            logger.warning(f"   ⚠️ Using safety default entry price: ${real_entry_price:.2f} (current * {SAFETY_DEFAULT_ENTRY_MULTIPLIER})")
                            logger.warning(f"   🔴 This position will be flagged as losing and exited aggressively")
                        
                        if active_broker and hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                            try:
                                # Calculate position size
                                size_usd = quantity * current_price
                                
                                # Track the position with real or estimated entry price
                                # Set aggressive exit parameters for auto-imported positions
                                auto_import_success = active_broker.position_tracker.track_entry(
                                    symbol=symbol,
                                    entry_price=real_entry_price,
                                    quantity=quantity,
                                    size_usd=size_usd,
                                    strategy="AUTO_IMPORTED"
                                )
                                
                                if auto_import_success:
                                    # Compute real PnL immediately
                                    immediate_pnl = ((current_price - real_entry_price) / real_entry_price) * 100
                                    logger.info(f"   ✅ AUTO-IMPORTED: {symbol} @ ${real_entry_price:.2f}")
                                    logger.info(f"   💰 Immediate P&L: {immediate_pnl:+.2f}%")
                                    logger.info(f"   🔴 Aggressive exits enabled: force_stop_loss=True, max_loss_pct=1.5%")
                                    
                                    # AUTO-IMPORTED LOSERS ARE EXITED FIRST
                                    # If position is immediately losing, queue it for exit
                                    if immediate_pnl < 0:
                                        logger.warning(f"   🚨 AUTO-IMPORTED LOSER: {symbol} at {immediate_pnl:.2f}%")
                                        logger.warning(f"   💥 Queuing for IMMEDIATE EXIT in next cycle")
                                    
                                    logger.info(f"      Position now tracked - will use profit targets in next cycle")
                                    logger.info(f"   ✅ AUTO-IMPORTED: {symbol} @ ${current_price:.2f} (P&L will start from $0) | "
                                              f"⚠️  WARNING: This position may have been losing before auto-import! | "
                                              f"Position now tracked - will evaluate exit in next cycle")
                                    
                                    # Mark that this position was just imported - skip exits this cycle
                                    just_auto_imported = True
                                    
                                    # Re-fetch position data to get accurate tracking info
                                    # This ensures control flow variables reflect actual state
                                    try:
                                        tracked_position = active_broker.position_tracker.get_position(symbol)
                                        if tracked_position:
                                            entry_price_available = True
                                            
                                            # Get entry time from newly tracked position
                                            entry_time = tracked_position.get('first_entry_time')
                                            if entry_time:
                                                try:
                                                    entry_dt = datetime.fromisoformat(entry_time)
                                                    now = datetime.now()
                                                    position_age_hours = (now - entry_dt).total_seconds() / 3600
                                                    entry_time_available = True
                                                except Exception:
                                                    # Just imported, so age should be ~0
                                                    entry_time_available = True
                                                    position_age_hours = 0
                                            
                                            logger.info(f"      Position verified in tracker - aggressive exits disabled")
                                    except Exception as verify_err:
                                        logger.warning(f"      Could not verify imported position: {verify_err}")
                                        # Still mark as available since track_entry succeeded
                                        entry_price_available = True
                                else:
                                    logger.error(f"   ❌ Auto-import failed for {symbol} - will use fallback exit logic")
                            except Exception as import_err:
                                logger.error(f"   ❌ Error auto-importing {symbol}: {import_err}")
                                logger.error(f"      Will use fallback exit logic")
                        
                        # If auto-import failed or not available, use fallback logic
                        if not auto_import_success:
                            logger.warning(f"      💡 Auto-import unavailable - using fallback exit logic")
                            
                            # CRITICAL FIX: For positions without entry price, use technical indicators
                            # to determine if position is weakening (RSI < 52, price < EMA9)
                            # This conservative exit strategy prevents holding potentially losing positions
                            
                            # Check if position was entered recently (less than 1 hour ago)
                            # If not, it's likely an old position that should be exited
                            if entry_time_available:
                                # We have time but no price - unusual, but use time-based exit
                                if position_age_hours >= MAX_POSITION_HOLD_HOURS:
                                    logger.warning(f"   ⏰ FALLBACK TIME EXIT: {symbol} held {position_age_hours:.1f}h (max: {MAX_POSITION_HOLD_HOURS}h)")
                                    positions_to_exit.append({
                                        'symbol': symbol,
                                        'quantity': quantity,
                                        'reason': f'Time-based exit without entry price (held {position_age_hours:.1f}h)'
                                    })
                                    continue
                            else:
                                # No entry time AND no entry price - this is an orphaned position
                                # These are likely old positions from before tracking was implemented
                                # Be conservative: exit if position shows any signs of weakness
                                logger.warning(f"   ⚠️ ORPHANED POSITION: {symbol} has no entry price or time tracking")
                                logger.warning(f"      This position will be exited aggressively to prevent losses")
                    
                    # Get market data for analysis (use cached method to prevent rate limiting)
                    candles = self._get_cached_candles(symbol, '5m', 100, broker=active_broker)
                    if not candles or len(candles) < MIN_CANDLES_REQUIRED:
                        logger.warning(f"   ⚠️ Insufficient data for {symbol} ({len(candles) if candles else 0} candles, need {MIN_CANDLES_REQUIRED})")
                        # CRITICAL: Exit positions we can't analyze to prevent blind holding
                        logger.info(f"   🔴 NO DATA EXIT: {symbol} (cannot analyze market)")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': 'Insufficient market data for analysis'
                        })
                        continue
                    
                    # Convert to DataFrame
                    df = pd.DataFrame(candles)
                    
                    # CRITICAL: Ensure numeric types for OHLCV data
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                    # Calculate indicators for exit signal detection
                    logger.debug(f"   DEBUG candle types → close={type(df['close'].iloc[-1])}, open={type(df['open'].iloc[-1])}, volume={type(df['volume'].iloc[-1])}")
                    indicators = self.apex.calculate_indicators(df)
                    if not indicators:
                        # Can't analyze - exit to prevent blind holding
                        logger.warning(f"   ⚠️ No indicators for {symbol} - exiting")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': 'No indicators available'
                        })
                        continue
                    
                    # CRITICAL: Skip ALL exits for positions that were just auto-imported this cycle
                    # These positions have entry_price = current_price (P&L = $0), so evaluating them
                    # for ANY exit signals would defeat the purpose of auto-import
                    # Let them develop P&L for at least one full cycle before applying ANY exit rules
                    # This guard is placed early to protect against both orphaned and momentum-based exits
                    if just_auto_imported:
                        logger.info(f"   ⏭️  SKIPPING EXITS: {symbol} was just auto-imported this cycle")
                        logger.info(f"      Will evaluate exit signals in next cycle after P&L develops")
                        logger.info(f"      🔍 Note: If this position shows 0% P&L for multiple cycles, it may be a masked loser")
                        continue
                    
                    # MOMENTUM-BASED PROFIT TAKING (for positions without entry price)
                    # When we don't have entry price, use price momentum and trend reversal signals
                    # This helps lock in gains on strong moves and cut losses on weak positions
                    
                    rsi = scalar(indicators.get('rsi', pd.Series()).iloc[-1] if 'rsi' in indicators else DEFAULT_RSI)
                    
                    # CRITICAL FIX (Jan 16, 2026): ORPHANED POSITION PROTECTION
                    # Positions without entry prices are more likely to be losing trades
                    # Apply ULTRA-AGGRESSIVE exits to prevent holding losers
                    if not entry_price_available:
                        # For orphaned positions, exit on ANY weakness signal
                        # This includes: RSI < 52 (below neutral), price below any EMA, or any downtrend
                        
                        # Get EMAs for trend analysis
                        ema9 = indicators.get('ema_9', pd.Series()).iloc[-1] if 'ema_9' in indicators else current_price
                        ema21 = indicators.get('ema_21', pd.Series()).iloc[-1] if 'ema_21' in indicators else current_price
                        
                        # Exit if RSI below 52 (slightly below neutral) - indicates weakening momentum
                        if rsi < 52:
                            logger.warning(f"   🚨 ORPHANED POSITION EXIT: {symbol} (RSI={rsi:.1f} < 52, no entry price)")
                            logger.warning(f"      Exiting aggressively to prevent holding potential loser")
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': f'Orphaned position with weak RSI ({rsi:.1f}) - preventing loss'
                            })
                            continue
                        
                        # Exit if price is below EMA9 (short-term weakness)
                        if current_price < ema9:
                            logger.warning(f"   🚨 ORPHANED POSITION EXIT: {symbol} (price ${current_price:.2f} < EMA9 ${ema9:.2f})")
                            logger.warning(f"      Exiting aggressively to prevent holding potential loser")
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': f'Orphaned position below EMA9 - preventing loss'
                            })
                            continue
                        
                        # If orphaned position made it here, it's showing strength - still monitor closely
                        logger.info(f"   ✅ ORPHANED POSITION SHOWING STRENGTH: {symbol} (RSI={rsi:.1f}, price above EMA9)")
                        logger.info(f"      Will continue monitoring with strict exit criteria")
                    
                    # ULTRA AGGRESSIVE: Exit on multiple signals to lock gains faster
                    # Jan 13, 2026: AGGRESSIVE thresholds to sell positions before reversals eat profits
                    
                    # Strong overbought (RSI > 55) - likely near top, take profits
                    if rsi > RSI_OVERBOUGHT_THRESHOLD:
                        logger.info(f"   📈 RSI OVERBOUGHT EXIT: {symbol} (RSI={rsi:.1f})")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': f'RSI overbought ({rsi:.1f}) - locking gains'
                        })
                        continue
                    
                    # Moderate overbought (RSI > 50) + weak momentum = exit (TIGHTENED from 52)
                    # This catches positions that are up but losing steam
                    if rsi > 50:
                        # Check if price is below short-term EMA (momentum weakening)
                        ema9 = indicators.get('ema_9', pd.Series()).iloc[-1] if 'ema_9' in indicators else current_price
                        if current_price < ema9:
                            logger.info(f"   📉 MOMENTUM REVERSAL EXIT: {symbol} (RSI={rsi:.1f}, price below EMA9)")
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': f'Momentum reversal (RSI={rsi:.1f}, price<EMA9) - locking gains'
                            })
                            continue
                    
                    # NEW: Profit protection - exit if in profit zone (RSI 45-55) but price crosses below EMA9
                    # This prevents giving back profits when momentum shifts
                    # TIGHTENED range from 48-60 to 45-55 for earlier exits
                    if 45 < rsi < 55:
                        ema9 = indicators.get('ema_9', pd.Series()).iloc[-1] if 'ema_9' in indicators else current_price
                        ema21 = indicators.get('ema_21', pd.Series()).iloc[-1] if 'ema_21' in indicators else current_price
                        # If price crosses below both EMAs, momentum is shifting - protect gains
                        if current_price < ema9 and current_price < ema21:
                            logger.info(f"   🔻 PROFIT PROTECTION EXIT: {symbol} (RSI={rsi:.1f}, price below both EMAs)")
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': f'Profit protection (RSI={rsi:.1f}, bearish cross) - locking gains'
                            })
                            continue
                    
                    # Oversold (RSI < 45) - prevent further losses (TIGHTENED from 40)
                    if rsi < RSI_OVERSOLD_THRESHOLD:
                        logger.info(f"   📉 RSI OVERSOLD EXIT: {symbol} (RSI={rsi:.1f}) - cutting losses")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': f'RSI oversold ({rsi:.1f}) - cutting losses'
                        })
                        continue
                    
                    # Moderate oversold (RSI < 50) + downtrend = exit (TIGHTENED from 48)
                    # This catches positions that are down and still falling
                    if rsi < 50:
                        # Check if price is in downtrend (below EMA21)
                        ema21 = indicators.get('ema_21', pd.Series()).iloc[-1] if 'ema_21' in indicators else current_price
                        if current_price < ema21:
                            logger.info(f"   📉 DOWNTREND EXIT: {symbol} (RSI={rsi:.1f}, price below EMA21)")
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': f'Downtrend exit (RSI={rsi:.1f}, price<EMA21) - cutting losses'
                            })
                            continue
                    
                    # Check for weak market conditions (exit signal)
                    # This protects capital even without knowing entry price
                    allow_trade, trend, market_reason = self.apex.check_market_filter(df, indicators)
                    
                    # AGGRESSIVE: If market conditions deteriorate, exit immediately
                    if not allow_trade:
                        logger.info(f"   ⚠️ Market conditions weak: {market_reason}")
                        logger.info(f"   💰 MARKING {symbol} for concurrent exit")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': market_reason
                        })
                        continue
                    
                    # If we get here, position passes all checks - keep it
                    logger.info(f"   ✅ {symbol} passing all checks (RSI={rsi:.1f}, trend={trend})")
                    
                except Exception as e:
                    logger.error(f"   Error analyzing position {symbol}: {e}", exc_info=True)
                
                # Rate limiting: Add delay after each position check to prevent 429 errors
                # Skip delay after the last position
                if position_idx < len(current_positions) - 1:
                    jitter = random.uniform(0, 0.05)  # 0-50ms jitter
                    time.sleep(POSITION_CHECK_DELAY + jitter)
            
            # CRITICAL: If still over cap after normal exit analysis, force-sell weakest remaining positions
            # Position cap set to 8 maximum concurrent positions
            if len(current_positions) > MAX_POSITIONS_ALLOWED and len(positions_to_exit) < (len(current_positions) - MAX_POSITIONS_ALLOWED):
                logger.warning(f"🚨 STILL OVER CAP: Need to sell {len(current_positions) - MAX_POSITIONS_ALLOWED - len(positions_to_exit)} more positions")
                
                # Identify positions not yet marked for exit
                symbols_to_exit = {p['symbol'] for p in positions_to_exit}
                remaining_positions = [p for p in current_positions if p.get('symbol') not in symbols_to_exit]
                
                # Sort by USD value (smallest first - easiest to exit and lowest capital impact)
                # CRITICAL FIX: Add None-check safety guard for price fetching in sort key
                def get_position_value(p):
                    """Calculate position value with None-check safety."""
                    symbol = p.get('symbol', '')
                    quantity = p.get('quantity', 0)
                    price = active_broker.get_current_price(symbol)
                    # Return 0 if price is None to sort invalid positions first
                    return quantity * (price if price is not None else 0)
                
                remaining_sorted = sorted(remaining_positions, key=get_position_value)
                
                # Force-sell smallest positions to get under cap
                positions_needed = (len(current_positions) - MAX_POSITIONS_ALLOWED) - len(positions_to_exit)
                for pos_idx, pos in enumerate(remaining_sorted[:positions_needed]):
                    symbol = pos.get('symbol')
                    quantity = pos.get('quantity', 0)
                    try:
                        price = active_broker.get_current_price(symbol)
                        
                        # CRITICAL FIX: Add None-check safety guard
                        # Prevents ghost positions from invalid price fetches
                        if price is None or price == 0:
                            logger.error(f"   ❌ Price fetch failed for {symbol} — symbol mismatch")
                            logger.error(f"   💡 This position may be unmanageable due to incorrect broker symbol format")
                            logger.warning(f"   🔴 FORCE-EXIT anyway: {symbol} (price unknown)")
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': 'Over position cap (price fetch failed - symbol mismatch)'
                            })
                            continue
                        
                        value = quantity * price
                        logger.warning(f"   🔴 FORCE-EXIT to meet cap: {symbol} (${value:.2f})")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': f'Over position cap (${value:.2f})'
                        })
                    except Exception as price_err:
                        # Still add even if price fetch fails
                        logger.warning(f"   ⚠️ Could not get price for {symbol}: {price_err}")
                        positions_to_exit.append({
                            'symbol': symbol,
                            'quantity': quantity,
                            'reason': 'Over position cap'
                        })
                    
                    # Rate limiting: Add delay after each price check (except last one)
                    if pos_idx < positions_needed - 1:
                        jitter = random.uniform(0, 0.05)  # 0-50ms jitter
                        time.sleep(POSITION_CHECK_DELAY + jitter)
            
            # CRITICAL FIX: Now sell ALL positions concurrently (not one at a time)
            if positions_to_exit:
                logger.info(f"")
                logger.info(f"🔴 CONCURRENT EXIT: Selling {len(positions_to_exit)} positions NOW")
                logger.info(f"="*80)
                
                for i, pos_data in enumerate(positions_to_exit, 1):
                    symbol = pos_data['symbol']
                    quantity = pos_data['quantity']
                    reason = pos_data['reason']
                    
                    logger.info(f"[{i}/{len(positions_to_exit)}] Selling {symbol} ({reason})")
                    
                    # CRITICAL FIX (Jan 10, 2026): Validate symbol before placing order
                    # Prevents "ProductID is invalid" errors
                    if not symbol or not isinstance(symbol, str):
                        logger.error(f"  ❌ SKIPPING: Invalid symbol (value: {symbol}, type: {type(symbol)})")
                        continue
                    
                    try:
                        result = active_broker.place_market_order(
                            symbol=symbol,
                            side='sell',
                            quantity=quantity,
                            size_type='base'
                        )
                        if result and result.get('status') not in ['error', 'unfilled']:
                            logger.info(f"  ✅ {symbol} SOLD successfully!")
                            # ✅ FIX #3: EXPLICIT SELL CONFIRMATION LOG
                            # If this was a stop-loss exit, log it clearly
                            if 'stop loss' in reason.lower():
                                logger.info(f"  ✅ SOLD {symbol} @ market due to stop loss")
                            # Track the exit in position tracker
                            if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                active_broker.position_tracker.track_exit(symbol, quantity)
                            # Remove from unsellable dict if it was there (position grew and became sellable)
                            if symbol in self.unsellable_positions:
                                del self.unsellable_positions[symbol]
                        else:
                            error_msg = result.get('error', result.get('message', 'Unknown')) if result else 'No response'
                            error_code = result.get('error') if result else None
                            logger.error(f"  ❌ {symbol} sell failed: {error_msg}")
                            logger.error(f"     Full result: {result}")
                            
                            # CRITICAL FIX (Jan 10, 2026): Handle INVALID_SYMBOL errors
                            # These indicate the symbol format is wrong or the product doesn't exist
                            is_invalid_symbol = (
                                error_code == 'INVALID_SYMBOL' or
                                'INVALID_SYMBOL' in str(error_msg) or
                                'invalid symbol' in str(error_msg).lower()
                            )
                            if is_invalid_symbol:
                                logger.error(f"     ⚠️ Symbol {symbol} is invalid or unsupported")
                                logger.error(f"     💡 This position will be skipped for 24 hours")
                                self.unsellable_positions[symbol] = time.time()
                                continue
                            
                            # If it's a dust/too-small position, mark it as unsellable to prevent infinite retries
                            # Check both error code and message for robustness
                            is_size_error = (
                                error_code == 'INVALID_SIZE' or 
                                'INVALID_SIZE' in str(error_msg) or 
                                'too small' in str(error_msg).lower() or
                                'minimum' in str(error_msg).lower()
                            )
                            if is_size_error:
                                logger.warning(f"     💡 Position {symbol} is too small to sell via API - marking as dust")
                                logger.warning(f"     💡 Will retry after 24 hours in case position grows")
                                self.unsellable_positions[symbol] = time.time()
                    except Exception as sell_err:
                        logger.error(f"  ❌ {symbol} exception during sell: {sell_err}")
                        logger.error(f"     Error type: {type(sell_err).__name__}")
                        logger.error(f"     Traceback: {traceback.format_exc()}")
                    
                    # Rate limiting: Add delay after each sell order (except the last one)
                    if i < len(positions_to_exit):
                        jitter = random.uniform(0, 0.1)  # 0-100ms jitter
                        time.sleep(SELL_ORDER_DELAY + jitter)
                
                logger.info(f"="*80)
                logger.info(f"✅ Concurrent exit complete: {len(positions_to_exit)} positions processed")
                logger.info(f"")
            
            # STEP 2: Look for new entry opportunities (only if entries allowed)
            # USER accounts NEVER generate entry signals - they receive signals via CopyTradeEngine
            # Only MASTER accounts scan markets and generate buy signals
            # PROFITABILITY FIX: Use module-level constants for consistency
            
            # ENHANCED LOGGING (Jan 22, 2025): Show broker-aware condition checklist for trade execution
            logger.info("")
            logger.info("═" * 80)
            logger.info("🎯 TRADE EXECUTION CONDITION CHECKLIST (BROKER-AWARE)")
            logger.info("═" * 80)
            
            if user_mode:
                # USER MODE: Skip market scanning and entry signal generation entirely
                logger.info("   ✅ Mode: USER (copy trading only)")
                logger.info("   ⏭️  RESULT: Skipping market scan (signals from copy trade engine)")
                logger.info("   ℹ️  USER accounts NEVER generate independent entry signals")
                logger.info("   ℹ️  USER accounts ONLY execute copied trades from MASTER")
                logger.info("═" * 80)
                logger.info("")
            else:
                logger.info("   ✅ Mode: MASTER (full strategy execution)")
                logger.info(f"   📊 Current positions: {len(current_positions)}/{MAX_POSITIONS_ALLOWED}")
                logger.info(f"   💰 Account balance: ${account_balance:.2f}")
                logger.info(f"   💵 Minimum to trade: ${MIN_BALANCE_TO_TRADE_USD:.2f}")
                logger.info(f"   🚫 Entries blocked: {entries_blocked}")
                logger.info("")
                
                # Check each condition individually
                can_enter = True
                skip_reasons = []
                
                if entries_blocked:
                    can_enter = False
                    skip_reasons.append("STOP_ALL_ENTRIES.conf is active")
                    logger.warning("   ❌ CONDITION FAILED: Entry blocking is active")
                else:
                    logger.info("   ✅ CONDITION PASSED: Entry blocking is OFF")
                
                if len(current_positions) >= MAX_POSITIONS_ALLOWED:
                    can_enter = False
                    skip_reasons.append(f"Position cap reached ({len(current_positions)}/{MAX_POSITIONS_ALLOWED})")
                    logger.warning(f"   ❌ CONDITION FAILED: Position cap reached ({len(current_positions)}/{MAX_POSITIONS_ALLOWED})")
                else:
                    logger.info(f"   ✅ CONDITION PASSED: Under position cap ({len(current_positions)}/{MAX_POSITIONS_ALLOWED})")
                
                if account_balance < MIN_BALANCE_TO_TRADE_USD:
                    can_enter = False
                    skip_reasons.append(f"Insufficient balance (${account_balance:.2f} < ${MIN_BALANCE_TO_TRADE_USD:.2f})")
                    logger.warning(f"   ❌ CONDITION FAILED: Insufficient balance (${account_balance:.2f} < ${MIN_BALANCE_TO_TRADE_USD:.2f})")
                else:
                    logger.info(f"   ✅ CONDITION PASSED: Sufficient balance (${account_balance:.2f} >= ${MIN_BALANCE_TO_TRADE_USD:.2f})")
                
                # BROKER-AWARE ENTRY GATING (Jan 22, 2025)
                # Check broker eligibility - must not be in EXIT_ONLY mode and meet balance requirements
                logger.info("")
                logger.info("   🏦 BROKER ELIGIBILITY CHECK:")
                
                # Get all available brokers for selection
                all_brokers = {}
                if hasattr(self, 'multi_account_manager') and self.multi_account_manager:
                    all_brokers = getattr(self.multi_account_manager, 'master_brokers', {})
                
                # Add current active broker if not in multi_account_manager
                if active_broker and hasattr(active_broker, 'broker_type'):
                    all_brokers[active_broker.broker_type] = active_broker
                
                # Select best broker for entry based on priority
                entry_broker, entry_broker_name, broker_eligibility = self._select_entry_broker(all_brokers)
                
                # Log broker eligibility status for all brokers
                for broker_name, status in broker_eligibility.items():
                    if "Eligible" in status:
                        logger.info(f"      ✅ {broker_name.upper()}: {status}")
                    elif "Not configured" in status:
                        logger.debug(f"      ⚪ {broker_name.upper()}: {status}")
                    else:
                        logger.warning(f"      ❌ {broker_name.upper()}: {status}")
                
                if not entry_broker:
                    can_enter = False
                    skip_reasons.append("No eligible broker for entry (all in EXIT_ONLY or below minimum balance)")
                    logger.warning(f"   ❌ CONDITION FAILED: No eligible broker for entry")
                    logger.warning(f"      💡 All brokers are either in EXIT-ONLY mode or below minimum balance")
                else:
                    logger.info(f"   ✅ CONDITION PASSED: {entry_broker_name.upper()} available for entry")
                    # Update active_broker to use the selected entry broker
                    active_broker = entry_broker
                
                logger.info("")
                logger.info("═" * 80)
                
                if can_enter:
                    logger.info(f"🟢 RESULT: CONDITIONS PASSED FOR {entry_broker_name.upper()}")
                    logger.info("═" * 80)
                    logger.info("")
                else:
                    logger.warning("🔴 RESULT: CONDITIONS FAILED - SKIPPING MARKET SCAN")
                    logger.warning(f"   Reasons: {', '.join(skip_reasons)}")
                    logger.warning("═" * 80)
                    logger.warning("")
            
            # Continue with market scanning if conditions passed
            if not user_mode and not entries_blocked and len(current_positions) < MAX_POSITIONS_ALLOWED and account_balance >= MIN_BALANCE_TO_TRADE_USD and can_enter:
                logger.info(f"🔍 Scanning for new opportunities (positions: {len(current_positions)}/{MAX_POSITIONS_ALLOWED}, balance: ${account_balance:.2f}, min: ${MIN_BALANCE_TO_TRADE_USD})...")
                
                # Get top market candidates (limit scan to prevent timeouts)
                try:
                    # Get list of all products (with caching to reduce API calls)
                    current_time = time.time()
                    if (not self.all_markets_cache or 
                        current_time - self.markets_cache_time > self.MARKETS_CACHE_TTL):
                        logger.info("   🔄 Refreshing market list from API...")
                        all_products = active_broker.get_all_products()
                        if all_products:
                            # FIX #3 (Jan 20, 2026): Filter Kraken markets BEFORE caching
                            # At startup: kraken_markets = [m for m in all_markets if kraken.supports_symbol(m)]
                            # Then scan ONLY these filtered markets
                            broker_name = self._get_broker_name(active_broker)
                            if broker_name == 'kraken':
                                original_count = len(all_products)
                                all_products = [
                                    sym for sym in all_products 
                                    if sym.endswith('/USD') or sym.endswith('/USDT') or 
                                       sym.endswith('-USD') or sym.endswith('-USDT')
                                ]
                                filtered_count = original_count - len(all_products)
                                logger.info(f"   🔍 Kraken market filter: {filtered_count} unsupported symbols removed at startup")
                                logger.info(f"      Kraken markets cached: {len(all_products)} (*/USD and */USDT pairs ONLY)")
                            
                            self.all_markets_cache = all_products
                            self.markets_cache_time = current_time
                            logger.info(f"   ✅ Cached {len(all_products)} markets")
                        else:
                            logger.warning("   ⚠️  No products available from API")
                            return
                    else:
                        all_products = self.all_markets_cache
                        cache_age = int(current_time - self.markets_cache_time)
                        logger.info(f"   ✅ Using cached market list ({len(all_products)} markets, age: {cache_age}s)")
                    
                    if not all_products:
                        logger.warning("   No products available for scanning")
                        return
                    
                    # Use rotation to scan different markets each cycle
                    markets_to_scan = self._get_rotated_markets(all_products)
                    
                    # FIX #3 (Jan 20, 2026): Kraken markets already filtered at startup
                    # No need to filter again during scan - markets_to_scan already contains only supported pairs
                    scan_limit = len(markets_to_scan)
                    logger.info(f"   Scanning {scan_limit} markets (batch rotation mode)...")
                    
                    # Adaptive rate limiting: track consecutive errors (429, 403, or no data)
                    # UPDATED (Jan 10, 2026): Distinguish invalid symbols from genuine errors
                    rate_limit_counter = 0
                    error_counter = 0  # Track total errors including exceptions
                    invalid_symbol_counter = 0  # Track invalid/delisted symbols (don't count as errors)
                    max_consecutive_rate_limits = 2  # CRITICAL FIX (Jan 10): Reduced from 3 - activate circuit breaker faster
                    max_total_errors = 4  # CRITICAL FIX (Jan 10): Reduced from 5 - stop scan earlier to prevent API ban
                    
                    # Track filtering reasons for debugging
                    filter_stats = {
                        'total': 0,
                        'insufficient_data': 0,
                        'smart_filter': 0,
                        'market_filter': 0,
                        'no_entry_signal': 0,
                        'position_too_small': 0,
                        'signals_found': 0,
                        'rate_limited': 0,
                        'cache_hits': 0
                    }
                    
                    for i, symbol in enumerate(markets_to_scan):
                        filter_stats['total'] += 1
                        try:
                            # FIX #1: BLACKLIST CHECK - Skip disabled pairs immediately
                            if symbol in DISABLED_PAIRS:
                                logger.debug(f"   ⛔ SKIPPING {symbol}: Blacklisted pair (spread > profit edge)")
                                continue
                            
                            # CRITICAL: Add delay BEFORE fetching candles to prevent rate limiting
                            # This is in addition to the delay after processing (line ~1201)
                            # Pre-delay ensures we never make requests too quickly in succession
                            if i > 0:  # Don't delay before first market
                                jitter = random.uniform(0, 0.3)  # Add 0-300ms jitter
                                time.sleep(MARKET_SCAN_DELAY + jitter)
                            
                            # Get candles with caching to reduce duplicate API calls
                            candles = self._get_cached_candles(symbol, '5m', 100, broker=active_broker)
                            
                            # Check if we got candles or if rate limited
                            if not candles:
                                # Empty candles could be:
                                # 1. Invalid/delisted symbol (don't count as error)
                                # 2. Rate limited (count as error)
                                # 3. No data available (count as error)
                                # We assume invalid symbol if we get consistent empty responses
                                
                                # Note: Invalid symbols are caught in get_candles() and return []
                                # So if we get here with no candles, it's likely rate limiting or no data
                                # We still increment counters but will check for invalid symbols in exceptions below
                                rate_limit_counter += 1
                                error_counter += 1
                                filter_stats['insufficient_data'] += 1
                                
                                # Degrade API health score on errors
                                self.api_health_score = max(0, self.api_health_score - 5)
                                
                                logger.debug(f"   {symbol}: No candles returned (may be rate limited or no data)")
                                
                                # GLOBAL CIRCUIT BREAKER: If too many total errors, stop scanning entirely
                                if error_counter >= max_total_errors:
                                    filter_stats['rate_limited'] += 1
                                    broker_name = self._get_broker_name(active_broker)
                                    logger.error(f"   🚨 GLOBAL CIRCUIT BREAKER: {error_counter} total errors - stopping scan to prevent API block")
                                    logger.error(f"   Exchange: {broker_name} | API health: {self.api_health_score}%")
                                    logger.error(f"   💤 Waiting 30s for API to fully recover before next cycle...")
                                    logger.error(f"   💡 TIP: Enable additional exchanges (Kraken, OKX, Binance) to distribute load")
                                    logger.error(f"   📖 See MULTI_EXCHANGE_TRADING_GUIDE.md for setup instructions")
                                    self.api_health_score = max(0, self.api_health_score - 20)  # Major penalty
                                    time.sleep(30.0)  # CRITICAL FIX (Jan 10): Increased from 20s to 30s for better recovery
                                    break  # Exit the market scan loop entirely
                                
                                # If we're getting many consecutive failures, assume rate limiting
                                if rate_limit_counter >= max_consecutive_rate_limits:
                                    filter_stats['rate_limited'] += 1
                                    logger.warning(f"   ⚠️ Possible rate limiting detected ({rate_limit_counter} consecutive failures)")
                                    logger.warning(f"   🛑 CIRCUIT BREAKER: Pausing for 15s to allow API to recover...")
                                    self.api_health_score = max(0, self.api_health_score - 10)  # Moderate penalty
                                    time.sleep(15.0)  # CRITICAL FIX (Jan 10): Decreased from 20s to 15s for consistency
                                    rate_limit_counter = 0  # Reset counter after delay
                                continue
                            elif len(candles) < 100:
                                rate_limit_counter = 0  # Reset on partial success
                                self.api_health_score = min(100, self.api_health_score + 1)  # Small recovery
                                filter_stats['insufficient_data'] += 1
                                logger.debug(f"   {symbol}: Insufficient candles ({len(candles)}/100)")
                                continue
                            else:
                                # Success! Reset rate limit counter and improve health
                                rate_limit_counter = 0
                                self.api_health_score = min(100, self.api_health_score + 2)  # Gradual recovery
                            
                            # Convert to DataFrame
                            df = pd.DataFrame(candles)
                            
                            # CRITICAL: Ensure numeric types
                            for col in ['open', 'high', 'low', 'close', 'volume']:
                                if col in df.columns:
                                    df[col] = pd.to_numeric(df[col], errors='coerce')
                            
                            # FIX #4: PAIR QUALITY FILTER - Check spread, volume, and ATR before analyzing
                            # Only run if check_pair_quality is available (imported at module level)
                            if check_pair_quality is not None:
                                try:
                                    # Get current bid/ask for spread check
                                    current_price = df['close'].iloc[-1]
                                    
                                    # PLACEHOLDER: Estimate bid/ask from price
                                    # TODO: Replace with actual bid/ask from broker API for more accurate spread check
                                    # Most major pairs (BTC, ETH, SOL) have ~0.01-0.05% spread
                                    # This conservative estimate (0.1%) ensures we don't miss quality pairs
                                    estimated_spread_pct = 0.001  # Assume 0.1% spread for estimation
                                    bid_price = current_price * (1 - estimated_spread_pct / 2)
                                    ask_price = current_price * (1 + estimated_spread_pct / 2)
                                    
                                    # Calculate ATR percentage if available
                                    atr_pct = None
                                    if 'atr' in df.columns and len(df) > 0:
                                        atr_value = df['atr'].iloc[-1]
                                        if pd.notna(atr_value) and current_price > 0:
                                            atr_pct = atr_value / current_price
                                    
                                    # Check pair quality
                                    quality_check = check_pair_quality(
                                        symbol=symbol,
                                        bid_price=bid_price,
                                        ask_price=ask_price,
                                        atr_pct=atr_pct,
                                        max_spread_pct=0.0015,  # 0.15% max spread
                                        min_atr_pct=0.005,  # 0.5% minimum ATR
                                        disabled_pairs=DISABLED_PAIRS
                                    )
                                    
                                    if not quality_check['quality_acceptable']:
                                        reasons = ', '.join(quality_check['reasons_failed'])
                                        logger.debug(f"   ⛔ QUALITY FILTER: {symbol} failed - {reasons}")
                                        filter_stats['market_filter'] += 1
                                        continue
                                    else:
                                        logger.debug(f"   ✅ Quality check passed: {symbol}")
                                except Exception as quality_err:
                                    # If quality check fails, log warning but don't block trading
                                    logger.debug(f"   ⚠️ Quality check error for {symbol}: {quality_err}")
                            
                            # Analyze for entry
                            # PRO MODE: Use total capital instead of just free balance
                            sizing_balance = total_capital if self.pro_mode_enabled else account_balance
                            analysis = self.apex.analyze_market(df, symbol, sizing_balance)
                            action = analysis.get('action', 'hold')
                            reason = analysis.get('reason', '')
                            
                            # Track why we didn't trade
                            if action == 'hold':
                                if 'Insufficient data' in reason or 'candles' in reason:
                                    filter_stats['insufficient_data'] += 1
                                elif 'smart filter' in reason.lower() or 'volume too low' in reason.lower() or 'candle' in reason.lower():
                                    filter_stats['smart_filter'] += 1
                                    logger.debug(f"   {symbol}: Smart filter - {reason}")
                                elif 'ADX' in reason or 'Volume' in reason or 'Mixed signals' in reason:
                                    filter_stats['market_filter'] += 1
                                    logger.debug(f"   {symbol}: Market filter - {reason}")
                                else:
                                    filter_stats['no_entry_signal'] += 1
                                    logger.debug(f"   {symbol}: No signal - {reason}")
                                continue
                            
                            # Execute buy actions
                            if action in ['enter_long', 'enter_short']:
                                filter_stats['signals_found'] += 1
                                position_size = analysis.get('position_size', 0)
                                
                                # Calculate dynamic minimum based on account balance (OPTION 3)
                                min_position_size_dynamic = get_dynamic_min_position_size(account_balance)
                                
                                # PROFITABILITY WARNING: Small positions have lower profitability
                                # Fees are ~1.4% round-trip, so very small positions face significant fee pressure
                                # DYNAMIC MINIMUM: Position must meet max(2.00, balance * 0.15)
                                if position_size < min_position_size_dynamic:
                                    filter_stats['position_too_small'] += 1
                                    # FIX #3 (Jan 19, 2026): Explicit trade rejection logging
                                    logger.info(f"   ❌ Entry rejected for {symbol}")
                                    logger.info(f"      Reason: Position size ${position_size:.2f} < ${min_position_size_dynamic:.2f} minimum")
                                    logger.info(f"      💡 Dynamic minimum = max($2.00, ${account_balance:.2f} × 15%) = ${min_position_size_dynamic:.2f}")
                                    logger.info(f"      💡 Small positions face severe fee impact (~1.4% round-trip)")
                                    # Calculate break-even % needed: (fee_dollars / position_size) * 100
                                    breakeven_pct = (position_size * 0.014 / position_size) * 100 if position_size > 0 else 0
                                    logger.info(f"      📊 Would need {breakeven_pct:.1f}% gain just to break even on fees")
                                    continue
                                
                                # FIX #3 (Jan 20, 2026): Kraken-specific minimum position size check
                                # Kraken requires larger minimum position size due to fees
                                broker_name = self._get_broker_name(active_broker)
                                if broker_name == 'kraken' and position_size < MIN_POSITION_SIZE:
                                    filter_stats['position_too_small'] += 1
                                    logger.info(f"   ❌ Entry rejected for {symbol}")
                                    logger.info(f"      Reason: Kraken position size ${position_size:.2f} < ${MIN_POSITION_SIZE} minimum")
                                    logger.info(f"      💡 Kraken requires ${MIN_POSITION_SIZE} minimum (5% of ${MIN_KRAKEN_BALANCE} balance)")
                                    continue
                                
                                # Warn if position is very small but allowed
                                elif position_size < 2.0:
                                    logger.warning(f"   ⚠️  EXTREMELY SMALL POSITION: ${position_size:.2f} - profitability nearly impossible due to fees")
                                    logger.warning(f"      💡 URGENT: Fund account to $30+ for viable trading")
                                elif position_size < 5.0:
                                    logger.warning(f"   ⚠️  VERY SMALL POSITION: ${position_size:.2f} - profitability severely limited by fees")
                                    logger.warning(f"      💡 Recommended: Fund account to $30+ for better trading results")
                                elif position_size < 10.0:
                                    logger.warning(f"   ⚠️  Small position: ${position_size:.2f} - profitability may be limited by fees")
                                
                                # CRITICAL: Verify we're still under position cap
                                if len(current_positions) >= MAX_POSITIONS_ALLOWED:
                                    logger.warning(f"   ⚠️  Position cap ({MAX_POSITIONS_ALLOWED}) reached - STOP NEW ENTRIES")
                                    break
                                
                                # PRO MODE: Check if rotation is needed
                                needs_rotation = False
                                if self.pro_mode_enabled and self.rotation_manager and position_size > account_balance:
                                    logger.info(f"   🔄 PRO MODE: Position size ${position_size:.2f} exceeds free balance ${account_balance:.2f}")
                                    logger.info(f"   → Rotation needed: ${position_size - account_balance:.2f}")
                                    
                                    # Check if we can rotate
                                    can_rotate, rotate_reason = self.rotation_manager.can_rotate(
                                        total_capital=total_capital,
                                        free_balance=account_balance,
                                        current_positions=len(current_positions)
                                    )
                                    
                                    if can_rotate:
                                        logger.info(f"   ✅ Rotation allowed: {rotate_reason}")
                                        
                                        # Build position metrics for rotation scoring
                                        position_metrics = {}
                                        for pos in current_positions:
                                            pos_symbol = pos.get('symbol')
                                            pos_qty = pos.get('quantity', 0)
                                            
                                            try:
                                                pos_price = active_broker.get_current_price(pos_symbol)
                                                
                                                # CRITICAL FIX: Add None-check safety guard
                                                # Prevents errors from invalid price fetches
                                                if pos_price is None:
                                                    logger.error(f"   ❌ Price fetch failed for {pos_symbol} — symbol mismatch")
                                                    logger.error(f"   💡 Skipping position from rotation scoring due to invalid price")
                                                    continue
                                                
                                                pos_value = pos_qty * pos_price if pos_price > 0 else 0
                                                
                                                # Get position age if available
                                                pos_age_hours = 0
                                                if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                    tracked = active_broker.position_tracker.get_position(pos_symbol)
                                                    if tracked and tracked.get('first_entry_time'):
                                                        entry_dt = datetime.fromisoformat(tracked['first_entry_time'])
                                                        pos_age_hours = (datetime.now() - entry_dt).total_seconds() / 3600
                                                
                                                # Calculate P&L if entry price available
                                                pos_pnl_pct = 0.0
                                                if hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                                                    tracked = active_broker.position_tracker.get_position(pos_symbol)
                                                    if tracked and tracked.get('average_entry_price'):
                                                        entry_price = float(tracked['average_entry_price'])
                                                        if entry_price > 0:
                                                            pos_pnl_pct = ((pos_price - entry_price) / entry_price) * 100
                                                
                                                # Get RSI if available (from recent market data)
                                                pos_rsi = 50  # Neutral default
                                                try:
                                                    # Attempt to get recent RSI from market data
                                                    if hasattr(self, 'apex') and self.apex:
                                                        # Try to get recent candles and calculate RSI
                                                        recent_candles = active_broker.get_candles(pos_symbol, '5m', 50)
                                                        if recent_candles and len(recent_candles) >= 14:
                                                            df_temp = pd.DataFrame(recent_candles)
                                                            for col in ['close']:
                                                                if col in df_temp.columns:
                                                                    df_temp[col] = pd.to_numeric(df_temp[col], errors='coerce')
                                                            indicators = self.apex.calculate_indicators(df_temp)
                                                            if 'rsi' in indicators:
                                                                pos_rsi = indicators['rsi']
                                                except Exception:
                                                    # Keep default RSI if calculation fails
                                                    pass
                                                
                                                position_metrics[pos_symbol] = {
                                                    'value': pos_value,
                                                    'age_hours': pos_age_hours,
                                                    'pnl_pct': pos_pnl_pct,
                                                    'rsi': pos_rsi
                                                }
                                            except Exception:
                                                continue
                                        
                                        # Select positions to close for rotation
                                        needed_capital = position_size - account_balance
                                        positions_to_close = self.rotation_manager.select_positions_for_rotation(
                                            positions=current_positions,
                                            position_metrics=position_metrics,
                                            needed_capital=needed_capital,
                                            total_capital=total_capital
                                        )
                                        
                                        if positions_to_close:
                                            logger.info(f"   🔄 Closing {len(positions_to_close)} position(s) for rotation:")
                                            
                                            # Close selected positions
                                            closed_count = 0
                                            for pos_to_close in positions_to_close:
                                                close_symbol = pos_to_close.get('symbol')
                                                close_qty = pos_to_close.get('quantity')
                                                
                                                try:
                                                    logger.info(f"      Closing {close_symbol}: {close_qty:.8f}")
                                                    result = active_broker.place_market_order(
                                                        close_symbol,
                                                        'sell',
                                                        close_qty,
                                                        size_type='base'
                                                    )
                                                    
                                                    if result and result.get('status') not in ['error', 'unfilled']:
                                                        closed_count += 1
                                                        logger.info(f"      ✅ Closed {close_symbol} successfully")
                                                    else:
                                                        logger.warning(f"      ⚠️ Failed to close {close_symbol}")
                                                    
                                                    time.sleep(0.5)  # Small delay between closes
                                                    
                                                except Exception as close_err:
                                                    logger.error(f"      ❌ Error closing {close_symbol}: {close_err}")
                                            
                                            if closed_count > 0:
                                                logger.info(f"   ✅ Rotation complete: Closed {closed_count} positions")
                                                self.rotation_manager.record_rotation(success=True)
                                                
                                                # Update free balance after rotation
                                                try:
                                                    time.sleep(1.0)  # Wait for balances to update
                                                    account_balance = active_broker.get_account_balance()
                                                    logger.info(f"   💰 Updated free balance: ${account_balance:.2f}")
                                                except Exception:
                                                    pass
                                            else:
                                                logger.warning(f"   ⚠️ Rotation failed - no positions closed")
                                                self.rotation_manager.record_rotation(success=False)
                                                continue  # Skip this trade
                                        else:
                                            logger.warning(f"   ⚠️ No suitable positions for rotation")
                                            continue  # Skip this trade
                                    else:
                                        logger.warning(f"   ⚠️ Cannot rotate: {rotate_reason}")
                                        continue  # Skip this trade if rotation not allowed
                                
                                logger.info(f"   🎯 BUY SIGNAL: {symbol} - size=${position_size:.2f} - {analysis.get('reason', '')}")
                                success = self.apex.execute_action(analysis, symbol)
                                if success:
                                    logger.info(f"   ✅ Position opened successfully")
                                    break  # Only open one position per cycle
                                else:
                                    logger.error(f"   ❌ Failed to open position")
                        
                        except Exception as e:
                            # CRITICAL FIX (Jan 10, 2026): Distinguish invalid symbols from rate limits
                            # Invalid symbols should NOT trigger circuit breakers or count as errors
                            error_str = str(e).lower()
                            
                            # More specific patterns to avoid false positives
                            is_productid_invalid = 'productid is invalid' in error_str or 'product_id is invalid' in error_str
                            is_invalid_argument = '400' in error_str and 'invalid_argument' in error_str
                            is_invalid_product_symbol = (
                                'invalid' in error_str and 
                                ('product' in error_str or 'symbol' in error_str) and
                                ('not found' in error_str or 'does not exist' in error_str or 'unknown' in error_str)
                            )
                            
                            is_invalid_symbol = is_productid_invalid or is_invalid_argument or is_invalid_product_symbol
                            
                            if is_invalid_symbol:
                                # Invalid/delisted symbol - skip silently without counting as error
                                invalid_symbol_counter += 1
                                filter_stats['market_filter'] += 1  # Count as filtered, not error
                                logger.debug(f"   ⚠️ Invalid/delisted symbol: {symbol} - skipping")
                                continue
                            
                            # Count as error only if not an invalid symbol
                            error_counter += 1
                            logger.debug(f"   Error scanning {symbol}: {e}")
                            
                            # Check if it's a rate limit error
                            if '429' in str(e) or 'rate limit' in str(e).lower() or 'too many' in str(e).lower() or '403' in str(e):
                                filter_stats['rate_limited'] += 1
                                rate_limit_counter += 1
                                logger.warning(f"   ⚠️ Rate limit error on {symbol}: {e}")
                                
                                # GLOBAL CIRCUIT BREAKER: Too many errors = stop scanning
                                if error_counter >= max_total_errors:
                                    broker_name = self._get_broker_name(active_broker)
                                    logger.error(f"   🚨 GLOBAL CIRCUIT BREAKER: {error_counter} total errors - stopping scan")
                                    logger.error(f"   Exchange: {broker_name} | API health: {self.api_health_score}%")
                                    logger.error(f"   💤 Waiting 10s for API to fully recover...")
                                    logger.error(f"   💡 TIP: Enable additional exchanges (Kraken, OKX, Binance) to distribute load")
                                    logger.error(f"   📖 See MULTI_EXCHANGE_TRADING_GUIDE.md for setup instructions")
                                    time.sleep(10.0)
                                    break  # Exit market scan loop
                                
                                # Add extra delay to recover
                                if rate_limit_counter >= 3:
                                    logger.warning(f"   🛑 CIRCUIT BREAKER: Pausing for 8s to allow API rate limits to reset...")
                                    time.sleep(8.0)  # Increased from 5.0s
                                    rate_limit_counter = 0
                            continue
                    
                    # Note: Market scan delay is now applied BEFORE each candle fetch (see line ~1088)
                    # This ensures we never make requests too quickly in succession
                    # No post-delay needed since pre-delay is more effective at preventing rate limits
                    
                    # Log filtering summary
                    logger.info(f"   📊 Scan summary: {filter_stats['total']} markets scanned")
                    logger.info(f"      💡 Signals found: {filter_stats['signals_found']}")
                    logger.info(f"      📉 No data: {filter_stats['insufficient_data']}")
                    
                    # Report invalid symbols separately (informational, not errors)
                    if invalid_symbol_counter > 0:
                        logger.info(f"      ℹ️ Invalid/delisted symbols: {invalid_symbol_counter} (skipped)")
                    
                    if filter_stats['rate_limited'] > 0:
                        logger.warning(f"      ⚠️ Rate limited: {filter_stats['rate_limited']} times")
                    logger.info(f"      🔇 Smart filter: {filter_stats['smart_filter']}")
                    logger.info(f"      📊 Market filter: {filter_stats['market_filter']}")
                    logger.info(f"      🚫 No entry signal: {filter_stats['no_entry_signal']}")
                    logger.info(f"      💵 Position too small: {filter_stats['position_too_small']}")
                
                except Exception as e:
                    logger.error(f"Error during market scan: {e}", exc_info=True)
            else:
                # Enhanced diagnostic logging to understand why entries are blocked
                reasons = []
                if entries_blocked:
                    reasons.append("STOP_ALL_ENTRIES.conf exists")
                if len(current_positions) >= MAX_POSITIONS_ALLOWED:
                    reasons.append(f"Position cap reached ({len(current_positions)}/{MAX_POSITIONS_ALLOWED})")
                if account_balance < MIN_BALANCE_TO_TRADE_USD:
                    reasons.append(f"Balance ${account_balance:.2f} < ${MIN_BALANCE_TO_TRADE_USD} minimum (need buffer for fees)")
                
                reason_str = ", ".join(reasons) if reasons else "Unknown reason"
                logger.info(f"   Skipping new entries: {reason_str}")
            
            # Increment cycle counter for warmup tracking
            self.cycle_count += 1
            
        except Exception as e:
            # Never raise to keep bot loop alive
            logger.error(f"Error in trading cycle: {e}", exc_info=True)
    
    def record_trade_with_advanced_manager(self, symbol: str, profit_usd: float, is_win: bool):
        """
        Record a completed trade with the advanced trading manager.
        
        Args:
            symbol: Trading symbol
            profit_usd: Profit/loss in USD
            is_win: True if trade was profitable
        """
        # Record with broker failsafes for circuit breaker protection
        if hasattr(self, 'failsafes') and self.failsafes:
            try:
                pnl_pct = (profit_usd / 100.0) if profit_usd != 0 else 0.0  # Approximate percentage
                self.failsafes.record_trade_result(profit_usd, pnl_pct)
            except Exception as e:
                logger.warning(f"Failed to record trade in failsafes: {e}")
        
        # Record with market adaptation for learning
        if hasattr(self, 'market_adapter') and self.market_adapter:
            try:
                # Estimate hold time (default 30 minutes if not tracked)
                hold_time_minutes = 30
                current_regime = getattr(self.market_adapter, 'current_regime', None)
                if current_regime:
                    self.market_adapter.record_trade_performance(
                        regime=current_regime,
                        pnl_dollars=profit_usd,
                        hold_time_minutes=hold_time_minutes,
                        parameters_used={'symbol': symbol}
                    )
            except Exception as e:
                logger.warning(f"Failed to record trade in market adapter: {e}")
        
        # Record with advanced manager (original functionality)
        if not self.advanced_manager:
            return
        
        try:
            # Determine which exchange was used
            from advanced_trading_integration import ExchangeType
            
            # Default to Coinbase as it's the primary broker
            exchange = ExchangeType.COINBASE
            
            # Try to detect actual exchange if broker type is available
            if hasattr(self, 'broker') and self.broker:
                broker_type = getattr(self.broker, 'broker_type', None)
                if broker_type:
                    exchange_mapping = {
                        'coinbase': ExchangeType.COINBASE,
                        'okx': ExchangeType.OKX,
                        'kraken': ExchangeType.KRAKEN,
                        'binance': ExchangeType.BINANCE,
                        'alpaca': ExchangeType.ALPACA,
                    }
                    broker_name = str(broker_type.value).lower() if hasattr(broker_type, 'value') else str(broker_type).lower()
                    exchange = exchange_mapping.get(broker_name, ExchangeType.COINBASE)
            
            # Record the trade
            self.advanced_manager.record_completed_trade(
                exchange=exchange,
                profit_usd=profit_usd,
                is_win=is_win
            )
            
            logger.debug(f"Recorded trade in advanced manager: {symbol} profit=${profit_usd:.2f} win={is_win}")
            
        except Exception as e:
            logger.warning(f"Failed to record trade in advanced manager: {e}")
    
    def process_end_of_day(self):
        """
        Process end-of-day tasks for advanced trading features.
        
        Should be called once per day to:
        - Check if daily profit target was achieved
        - Trigger rebalancing if needed
        - Generate performance reports
        """
        if not self.advanced_manager:
            return
        
        try:
            # Process end-of-day in advanced manager
            self.advanced_manager.process_end_of_day()
            
            # Log current status
            current_target = self.advanced_manager.target_manager.get_current_target()
            progress = self.advanced_manager.target_manager.get_progress_summary()
            
            logger.info("=" * 70)
            logger.info("📊 END OF DAY SUMMARY")
            logger.info(f"   Current Target: ${current_target:.2f}/day")
            logger.info(f"   Progress: {progress}")
            logger.info("=" * 70)
            
        except Exception as e:
            logger.warning(f"Failed to process end-of-day tasks: {e}")
