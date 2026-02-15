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
from enum import Enum
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

# Import Market Readiness Gate for entry quality control
try:
    from market_readiness_gate import MarketReadinessGate, MarketMode
except ImportError:
    try:
        from bot.market_readiness_gate import MarketReadinessGate, MarketMode
    except ImportError:
        # Graceful fallback if market readiness gate not available
        MarketReadinessGate = None
        MarketMode = None
        logger.warning("⚠️ Market Readiness Gate not available - using legacy entry mode")

# Import Trade Quality Gate for Layer 2 improvements
try:
    from trade_quality_gate import TradeQualityGate
except ImportError:
    try:
        from bot.trade_quality_gate import TradeQualityGate
    except ImportError:
        TradeQualityGate = None

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

# Position adoption safety constants
# When entry price is missing from exchange, use current_price * this multiplier
# This creates an immediate small loss to trigger aggressive exit management
MISSING_ENTRY_PRICE_MULTIPLIER = 1.01  # 1% above current = -0.99% immediate P&L

# Maximum number of open orders to display in logs when positions are being adopted
MAX_DISPLAYED_ORDERS = 5  # Show first 5 orders, summarize remaining

# Import BrokerType and AccountType at module level for use throughout the class
# These are needed in _register_kraken_for_retry and other methods outside __init__
try:
    from broker_manager import BrokerType, AccountType, MINIMUM_TRADING_BALANCE
except ImportError:
    try:
        from bot.broker_manager import BrokerType, AccountType, MINIMUM_TRADING_BALANCE
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
            PLATFORM = "platform"
            USER = "user"

        # Also need MINIMUM_TRADING_BALANCE fallback
        MINIMUM_TRADING_BALANCE = 10.0  # Default minimum (updated from $25 for new tier structure)

# NIJA State Machine for Position Management (Feb 15, 2026)
# Formal state tracking to ensure deterministic behavior and proper invariants
class PositionManagementState(Enum):
    """
    Position management state machine for NIJA trading bot.
    
    States:
    - NORMAL: Trading normally, under position cap, entries allowed
    - DRAIN: Over position cap, actively draining excess positions, entries blocked
    - FORCED_UNWIND: Emergency exit mode, closing all positions immediately
    """
    NORMAL = "normal"
    DRAIN = "drain"
    FORCED_UNWIND = "forced_unwind"


class StateInvariantValidator:
    """
    System-level invariant validator for NIJA state machine.
    
    Validates critical invariants at state transitions to ensure system correctness:
    - Position count is always >= 0
    - Excess positions only exist in DRAIN or FORCED_UNWIND states
    - State transitions follow valid paths
    """
    
    @staticmethod
    def validate_state_invariants(state, num_positions, excess_positions, max_positions):
        """
        Validate system invariants for the current state.
        
        Args:
            state: Current PositionManagementState
            num_positions: Current number of open positions
            excess_positions: Number of positions over cap
            max_positions: Maximum allowed positions
            
        Raises:
            AssertionError: If any invariant is violated
        """
        # Invariant 1: Position count must be non-negative
        assert num_positions >= 0, f"INVARIANT VIOLATION: Position count is negative: {num_positions}"
        
        # Invariant 2: Excess positions must be non-negative
        assert excess_positions >= 0 or state == PositionManagementState.NORMAL, \
            f"INVARIANT VIOLATION: Negative excess in {state.value} mode: excess={excess_positions}"
        
        # Invariant 3: Excess calculation must be consistent
        calculated_excess = num_positions - max_positions
        assert excess_positions == calculated_excess, \
            f"INVARIANT VIOLATION: Excess mismatch: reported={excess_positions}, calculated={calculated_excess}"
        
        # Invariant 4: DRAIN mode should only be active when excess > 0
        if state == PositionManagementState.DRAIN:
            assert excess_positions > 0, \
                f"INVARIANT VIOLATION: DRAIN mode active but excess={excess_positions} (should be > 0)"
        
        # Invariant 5: NORMAL mode should only be active when excess <= 0
        if state == PositionManagementState.NORMAL:
            assert excess_positions <= 0, \
                f"INVARIANT VIOLATION: NORMAL mode active but excess={excess_positions} (should be <= 0)"
    
    @staticmethod
    def validate_state_transition(old_state, new_state, num_positions, excess_positions):
        """
        Validate that a state transition is valid.
        
        Args:
            old_state: Previous PositionManagementState
            new_state: New PositionManagementState
            num_positions: Current number of positions
            excess_positions: Number of positions over cap
            
        Returns:
            bool: True if transition is valid, False otherwise
        """
        # Define valid state transitions
        valid_transitions = {
            PositionManagementState.NORMAL: {PositionManagementState.DRAIN, PositionManagementState.FORCED_UNWIND},
            PositionManagementState.DRAIN: {PositionManagementState.NORMAL, PositionManagementState.FORCED_UNWIND},
            PositionManagementState.FORCED_UNWIND: {PositionManagementState.NORMAL, PositionManagementState.DRAIN},
        }
        
        # Allow self-transitions (staying in same state)
        if old_state == new_state:
            return True
        
        # Check if transition is in the allowed set
        if new_state not in valid_transitions.get(old_state, set()):
            logger.error(f"INVALID STATE TRANSITION: {old_state.value} → {new_state.value}")
            return False
        
        return True

# FIX #1: BLACKLIST PAIRS - Disable pairs that are not suitable for strategy
# XRP-USD is PERMANENTLY DISABLED due to negative profitability
# Load additional disabled pairs from environment variable
_env_disabled_pairs = os.getenv('DISABLED_PAIRS', '')
_additional_disabled = [p.strip() for p in _env_disabled_pairs.split(',') if p.strip()]
DISABLED_PAIRS = ["XRP-USD", "XRPUSD", "XRP-USDT"] + _additional_disabled  # Block all XRP pairs - net negative performance

# Load geographically restricted symbols from blacklist
try:
    from bot.restricted_symbols import get_restriction_manager
    _restriction_mgr = get_restriction_manager()
    _restricted_symbols = _restriction_mgr.get_all_restricted_symbols()
    if _restricted_symbols:
        logger.info(f"📋 Loaded {len(_restricted_symbols)} geographically restricted symbols")
        DISABLED_PAIRS.extend(_restricted_symbols)
except ImportError:
    try:
        from restricted_symbols import get_restriction_manager
        _restriction_mgr = get_restriction_manager()
        _restricted_symbols = _restriction_mgr.get_all_restricted_symbols()
        if _restricted_symbols:
            logger.info(f"📋 Loaded {len(_restricted_symbols)} geographically restricted symbols")
            DISABLED_PAIRS.extend(_restricted_symbols)
    except ImportError as e:
        logger.debug(f"Note: Could not load restriction blacklist: {e}")

# Load whitelist configuration for PLATFORM_ONLY mode (optional)
try:
    from bot.platform_only_config import is_whitelisted_symbol, WHITELISTED_ASSETS
    WHITELIST_ENABLED = os.getenv('ENABLE_SYMBOL_WHITELIST', 'false').lower() in ('true', '1', 'yes')
    if WHITELIST_ENABLED:
        logger.info(f"✅ Symbol whitelist ENABLED: {', '.join(WHITELISTED_ASSETS)}")
    else:
        logger.debug("Symbol whitelist available but not enabled (set ENABLE_SYMBOL_WHITELIST=true to enable)")
except ImportError:
    WHITELIST_ENABLED = False
    logger.debug("Note: Symbol whitelist not available (platform_only_config not found)")

# Time conversion constants
MINUTES_PER_HOUR = 60  # Minutes in one hour (used for time-based calculations)

# FIX #1: Removed default capital - MUST be set from live broker balance
# This placeholder is replaced with live multi-broker balance after connection
# Set to $0 to prevent any trading until real balance is loaded
PLACEHOLDER_CAPITAL = 0.0  # No default capital - MUST be set from live balance

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

# Broker balance fetch timeout constants (Jan 28, 2026)
# CRITICAL FIX: Increased from 20s to 45s to accommodate Kraken API timeout (30s) plus network overhead
# 45s chosen to allow: 30s Kraken API timeout + 15s network/serialization buffer
# Kraken get_account_balance makes 2 API calls (Balance + TradeBalance) with 1s minimum between calls
# Under production load, Kraken regularly takes 15-20s to respond (within 30s API timeout)
# If timeout occurs, cached balance is used as fallback (max age: 5 minutes)
BALANCE_FETCH_TIMEOUT = 45  # Maximum time to wait for balance fetch (must be > Kraken API timeout of 30s)
CACHED_BALANCE_MAX_AGE_SECONDS = 300  # Use cached balance if fresh (5 minutes max staleness)

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
# 🚨 CRITICAL FIX (Feb 4, 2026): Convert PROFIT_TARGETS to fractional format
# pnl_percent is in fractional format (0.02 = 2%), so targets must match
# Previous bug: targets were in percentage format (4.0 = 4%), causing profit-taking to NEVER fire
# Fix: Divide all targets by 100 to convert to fractional format

# 📈 CAPITAL TIER PROFIT LADDERS (Feb 4, 2026)
# Different capital tiers use different profit targets for optimal risk/reward
# Larger accounts can afford to wait for bigger wins
# Smaller accounts need to take profits more aggressively

# MICRO TIER ($10-$100): Aggressive profit-taking, build capital fast
PROFIT_TARGETS_MICRO = [
    (0.025, "Profit target +2.5% (Micro tier) - EXCELLENT"),
    (0.020, "Profit target +2.0% (Micro tier) - GOOD"),
    (0.015, "Profit target +1.5% (Micro tier) - ACCEPTABLE"),
    (0.012, "Profit target +1.2% (Micro tier) - MINIMAL"),
]

# SMALL TIER ($100-$1000): Balanced approach
PROFIT_TARGETS_SMALL = [
    (0.030, "Profit target +3.0% (Small tier) - EXCELLENT"),
    (0.025, "Profit target +2.5% (Small tier) - GOOD"),
    (0.020, "Profit target +2.0% (Small tier) - ACCEPTABLE"),
    (0.015, "Profit target +1.5% (Small tier) - MINIMAL"),
]

# MEDIUM TIER ($1000-$10000): Let winners run more
PROFIT_TARGETS_MEDIUM = [
    (0.040, "Profit target +4.0% (Medium tier) - MAJOR PROFIT"),
    (0.030, "Profit target +3.0% (Medium tier) - EXCELLENT"),
    (0.025, "Profit target +2.5% (Medium tier) - GOOD"),
    (0.020, "Profit target +2.0% (Medium tier) - ACCEPTABLE"),
]

# LARGE TIER ($10000+): Maximum profit potential
PROFIT_TARGETS_LARGE = [
    (0.050, "Profit target +5.0% (Large tier) - MAJOR PROFIT"),
    (0.040, "Profit target +4.0% (Large tier) - EXCELLENT"),
    (0.030, "Profit target +3.0% (Large tier) - GOOD"),
    (0.025, "Profit target +2.5% (Large tier) - ACCEPTABLE"),
]

# Default fallback targets (medium tier)
PROFIT_TARGETS = PROFIT_TARGETS_MEDIUM

# BROKER-SPECIFIC PROFIT TARGETS (Jan 27, 2026 - PROFITABILITY FIX)
# 🚨 CRITICAL FIX (Feb 4, 2026): All values converted to FRACTIONAL format (0.04 = 4%)
# Different brokers have different fee structures, requiring different profit targets
# These ensure NET profitability after fees for each broker
# PHILOSOPHY: "Little loss, major profit" - tight stops, wide profit targets
# Kraken fees: ~0.52% round-trip (0.26% taker fee x 2 sides)
# Using 0.6% in calculations for safety margin (includes spread)
PROFIT_TARGETS_KRAKEN = [
    (0.040, "Profit target +4.0% (Net +3.4% after 0.6% fees) - MAJOR PROFIT"),    # Major profit - let winners run
    (0.030, "Profit target +3.0% (Net +2.4% after 0.6% fees) - EXCELLENT"),       # Excellent profit
    (0.020, "Profit target +2.0% (Net +1.4% after 0.6% fees) - GOOD"),            # Good profit (preferred target)
    (0.015, "Profit target +1.5% (Net +0.9% after 0.6% fees) - ACCEPTABLE"),      # Acceptable profit
    (0.010, "Profit target +1.0% (Net +0.4% after 0.6% fees) - MINIMAL"),         # Bare minimum profit
]

# 🚨 COINBASE PROFIT FIX (Jan 2026) - ENSURE NET PROFITABILITY
# 🚨 CRITICAL FIX (Feb 4, 2026): All values converted to FRACTIONAL format (0.05 = 5%)
# Coinbase fees are 1.4% round-trip (0.7% entry + 0.7% exit)
# ALL profit targets must exceed 1.6% to ensure NET profitability after fees and spread
# REMOVED all loss-making "emergency exit" targets - these guaranteed losses
# PHILOSOPHY: Only take trades with positive risk/reward ratio
PROFIT_TARGETS_COINBASE = [
    (0.050, "Profit target +5.0% (Net +3.6% after 1.4% fees) - MAJOR PROFIT"),    # Major profit - let winners run
    (0.035, "Profit target +3.5% (Net +2.1% after 1.4% fees) - EXCELLENT"),       # Excellent profit
    (0.025, "Profit target +2.5% (Net +1.1% after 1.4% fees) - GOOD"),            # Good profit (preferred target)
    (0.020, "Profit target +2.0% (Net +0.6% after fees) - ACCEPTABLE"),           # Minimum acceptable profit
    (0.016, "Profit target +1.6% (Net +0.2% after fees) - MINIMAL"),              # Bare minimum (emergency only)
]

# PROFITABILITY FIX (Jan 27, 2026): Updated profit targets to ensure NET gains
# NIJA is for PROFIT - all targets now ensure positive returns after fees
# Fee structure: Coinbase 1.4% round-trip, Kraken 0.4% round-trip
# New targets: Coinbase 2.5%+ (net 1.1%+), Kraken 2.0%+ (net 1.6%+)
# Risk/Reward: Minimum 2:1 ratio enforced via stop loss sizing

# FIX #3: Minimum Profit Threshold (Updated for new targets)
# Calculate required profit = spread + fees + buffer before allowing exit
# Coinbase: ~0.7% taker fee x2 + ~0.2% spread = 1.6% round-trip
MIN_PROFIT_SPREAD = 0.002  # 0.2% estimated spread cost
MIN_PROFIT_FEES = 0.014  # 1.4% total fees (0.7% per side)
MIN_PROFIT_BUFFER = 0.002  # 0.2% safety buffer
MIN_PROFIT_THRESHOLD = 0.020  # 2.0% minimum profit (updated from 1.6% to match new targets)

# PROFIT PROTECTION: Updated for new profit targets (Jan 27, 2026)
# Allow slightly larger pullback since profit targets are higher
PROFIT_PROTECTION_ENABLED = True  # Enable profit protection system
PROFIT_PROTECTION_PULLBACK_FIXED = 0.008  # Allow 0.8% pullback (increased from 0.5%)
PROFIT_PROTECTION_MIN_PROFIT = 0.020  # Must exceed 2.0% for Coinbase before protection activates
PROFIT_PROTECTION_MIN_PROFIT_KRAKEN = 0.010  # Must exceed 1.0% for Kraken before protection activates
PROFIT_PROTECTION_NEVER_BREAKEVEN = True  # Never allow profitable positions to break even

# Stop loss thresholds - ULTRA-AGGRESSIVE (V7.4 FIX - Jan 19, 2026)
# CRITICAL: Exit ANY losing trade IMMEDIATELY (P&L < 0%)
# These thresholds are FAILSAFES only - primary exit is immediate on any loss
# Jan 19, 2026: Changed to immediate exit on ANY loss per user requirement
# Jan 13, 2026: Tightened to -1.0% to cut losses IMMEDIATELY
# Jan 19, 2026: 3-TIER STOP-LOSS SYSTEM for Kraken small balances
# Tier 1: Primary trading stop (-0.6% to -0.8%) - Real stop-loss for risk management
# Tier 2: Emergency micro-stop (-0.01%) - Logic failure prevention (not a trading stop)
# Tier 3: Catastrophic failsafe (-5.0%) - Last resort protection

# 🚨 STOP LOSS FIX (Jan 27, 2026) - PROPER RISK/REWARD RATIO
# Updated to ensure minimum 2:1 reward-to-risk ratio
# With profit targets of 2.5%+ (Coinbase) and 2.0%+ (Kraken),
# stop losses must be proportionally sized to maintain good risk/reward

# TIER 1: PRIMARY TRADING STOP-LOSS
# Updated Jan 28, 2026: Tightened stop-losses to -0.5% through -1.0% range
# Target: Average loss -0.6% per losing trade (ENHANCED_STRATEGY_GUIDE.md line 393)
# Kraken: With 2.0% profit target, improved risk/reward ratio
STOP_LOSS_PRIMARY_KRAKEN = -0.008  # -0.8% for Kraken (allows 2.5:1 ratio with 2% profit target - IMPROVED)
STOP_LOSS_PRIMARY_KRAKEN_MIN = -0.005  # -0.5% minimum (tighter for strong setups with low volatility)
STOP_LOSS_PRIMARY_KRAKEN_MAX = -0.010  # -1.0% maximum (was -1.2%, tightened for better capital preservation)

# Coinbase: With 2.5% profit target, improved risk/reward ratio
STOP_LOSS_PRIMARY_COINBASE = -0.010  # -1.0% primary stop for Coinbase (allows 2.5:1 ratio with 2.5% target - IMPROVED)
COINBASE_STOP_LOSS_MIN = -0.008  # -0.8% minimum (tighter for strong setups)
COINBASE_STOP_LOSS_MAX = -0.010  # -1.0% maximum (was -1.5%, tightened for better capital preservation)

# Remove the "exit on ANY loss" requirement - this was causing premature exits
COINBASE_EXIT_ANY_LOSS = False  # Allow positions to breathe, honor stop loss levels
COINBASE_MAX_HOLD_MINUTES = 60  # Increased from 30 to 60 minutes (allow time for profit)
COINBASE_PROFIT_LOCK_ENABLED = True  # Enable aggressive profit-taking on Coinbase

# TIER 2: EMERGENCY MICRO-STOP (Logic failure prevention)
# This is NOT a trading stop - it's a failsafe to prevent logic failures
# Examples: imported positions without entry price, calculation errors, data corruption
# Terminology: "Emergency micro-stop to prevent logic failures (not a trading stop)"
# CRITICAL FIX (Feb 3, 2026): Widened stops for crypto volatility (was -2%, now -1.5%)
# Crypto markets have 0.3-0.8% normal intraday volatility, -2% was too tight
STOP_LOSS_MICRO = -0.015  # -1.5% emergency micro-stop (was -2%, too tight for crypto)
STOP_LOSS_WARNING = -0.012  # -1.2% warn before hitting stop (early warning)
STOP_LOSS_THRESHOLD = -0.015  # -1.5% primary stop threshold (widened from -2%)

# TIER 3: CATASTROPHIC FAILSAFE
# Last resort protection - should NEVER be reached in normal operation
# NORMALIZED FORMAT: -0.05 = -5% (fractional format)
STOP_LOSS_EMERGENCY = -0.05  # EMERGENCY exit at -5% loss (FAILSAFE - absolute last resort)

# PROFITABILITY GUARD: Minimum loss threshold to reduce noise
# CRITICAL FIX (Feb 3, 2026): Lowered from -0.25% to -0.05% to avoid creating dead zone
# OLD VALUE: -0.0025 (-0.25%) created dead zone where stops wouldn't trigger
# NEW VALUE: -0.0005 (-0.05%) only filters bid/ask spread noise
MIN_LOSS_FLOOR = -0.0005  # -0.05% - only ignore bid/ask spread noise (was -0.25%, too high)

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
# Support override via MAX_CONCURRENT_POSITIONS environment variable for custom configurations
_max_positions_env = os.getenv('MAX_CONCURRENT_POSITIONS', '8')
try:
    MAX_POSITIONS_ALLOWED = int(_max_positions_env)
except ValueError:
    MAX_POSITIONS_ALLOWED = 8  # Default fallback
logger.info(f"📊 Max concurrent positions: {MAX_POSITIONS_ALLOWED}")

# Forced cleanup interval (cycles between cleanup runs)
# Default: 6 cycles (~15 minutes at 2.5 min/cycle) - For maximum safety optics
# Can be overridden via FORCED_CLEANUP_INTERVAL environment variable
_cleanup_interval_env = os.getenv('FORCED_CLEANUP_INTERVAL', '6')
try:
    FORCED_CLEANUP_INTERVAL = int(_cleanup_interval_env)
except ValueError:
    FORCED_CLEANUP_INTERVAL = 6  # Default fallback (15 minutes)
logger.debug(f"🧹 Forced cleanup interval: every {FORCED_CLEANUP_INTERVAL} cycles (~{FORCED_CLEANUP_INTERVAL * 2.5:.0f} minutes)")

# Optional: Cleanup after N trades executed (alternative/additional trigger)
# If set, cleanup runs after N trades OR every FORCED_CLEANUP_INTERVAL cycles (whichever comes first)
_cleanup_trades_env = os.getenv('FORCED_CLEANUP_AFTER_N_TRADES', '')
try:
    FORCED_CLEANUP_AFTER_N_TRADES = int(_cleanup_trades_env) if _cleanup_trades_env else None
    if FORCED_CLEANUP_AFTER_N_TRADES:
        logger.debug(f"🧹 Forced cleanup also triggers after {FORCED_CLEANUP_AFTER_N_TRADES} trades executed")
except ValueError:
    FORCED_CLEANUP_AFTER_N_TRADES = None

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
# UPDATE (Jan 22, 2026): Aligned with new tier structure and $10 minimum trade size
# Kraken enforces $10 minimum trade size per exchange rules
MIN_KRAKEN_BALANCE = 10.0   # Minimum balance for Kraken to allow trading (updated from $25)
MIN_POSITION_SIZE = 10.0    # Minimum position size for Kraken ($10 minimum trade)

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
# UPDATE (Jan 22, 2026): Aligned with new tier structure and $10 Kraken minimum
BROKER_MIN_BALANCE = {
    BrokerType.COINBASE: 10.0,  # Coinbase minimum lowered to support SAVER tier
    BrokerType.KRAKEN: 10.0,    # Kraken minimum is $10 per exchange rules
    BrokerType.OKX: 10.0,       # Lower minimum for OKX
    BrokerType.BINANCE: 10.0,   # Lower minimum for Binance
}

# ============================================================================
# HEARTBEAT TRADE CONFIGURATION
# ============================================================================
# Heartbeat trades are tiny test trades executed periodically to verify:
# - Exchange connectivity is working
# - Order execution is functioning
# - API credentials are valid
# Useful for verification after deployment or to monitor exchange health
HEARTBEAT_TRADE_ENABLED = os.getenv('HEARTBEAT_TRADE', 'false').lower() in ('true', '1', 'yes')
HEARTBEAT_TRADE_SIZE_USD = float(os.getenv('HEARTBEAT_TRADE_SIZE', '5.50'))  # Minimum viable trade size
HEARTBEAT_TRADE_INTERVAL_SECONDS = int(os.getenv('HEARTBEAT_TRADE_INTERVAL', '600'))  # 10 minutes default

if HEARTBEAT_TRADE_ENABLED:
    logger.info(f"❤️  HEARTBEAT TRADE ENABLED: ${HEARTBEAT_TRADE_SIZE_USD:.2f} every {HEARTBEAT_TRADE_INTERVAL_SECONDS}s")
else:
    logger.debug("Heartbeat trade disabled (set HEARTBEAT_TRADE=true to enable)")

def call_with_timeout(func, args=(), kwargs=None, timeout_seconds=30):
    """
    Execute a function with a timeout. Returns (result, error).
    If timeout occurs, returns (None, TimeoutError).
    Default timeout is 30 seconds to accommodate production API latency.

    CRITICAL FIX (Jan 27, 2026): Fixed race condition where queue.get_nowait()
    could raise queue.Empty even after successful completion.
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

    t = Thread(target=worker, daemon=False)  # Changed to daemon=False to prevent premature termination
    t.start()
    t.join(timeout_seconds)

    if t.is_alive():
        # Thread still running after timeout
        return None, TimeoutError(f"Operation timed out after {timeout_seconds}s")

    # CRITICAL FIX: Use get() with small timeout instead of get_nowait()
    # FIX: Use get(timeout=1.0) instead of get_nowait() to prevent race condition
    # After thread.join(), there's a small window where result may not be in queue yet
    # 1.0s timeout is generous - actual queue write happens in <10ms
    try:
        ok, value = result_queue.get(timeout=1.0)
        return (value, None) if ok else (None, value)
    except queue.Empty:
        # This should never happen if thread completed, but handle it anyway
        return None, Exception("Worker thread completed but no result available")

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

        # Last Evaluated Trade Tracking (for UI panel)
        self.last_evaluated_trade = {
            'timestamp': None,
            'symbol': None,
            'signal': None,
            'action': None,  # 'executed', 'vetoed', 'evaluated'
            'veto_reasons': [],
            'entry_price': None,
            'position_size': None,
            'broker': None,
            'confidence': None,
            'rsi_9': None,
            'rsi_14': None
        }

        # Initialize safety controller (App Store compliance)
        try:
            from safety_controller import get_safety_controller, TradingMode
            self.safety = get_safety_controller()
            self.safety.log_status()
            
            # Store dry_run_mode for backward compatibility
            self.dry_run_mode = (self.safety.get_current_mode() == TradingMode.DRY_RUN)
        except ImportError:
            # Fallback if safety_controller not available
            logger.warning("⚠️ Safety controller not available - using legacy safety checks")
            self.safety = None
            self.dry_run_mode = os.getenv('DRY_RUN_MODE', 'false').lower() in ('true', '1', 'yes')
            if self.dry_run_mode:
                logger.info("=" * 70)
                logger.info("🎭 DRY-RUN SIMULATOR MODE ACTIVE")
                logger.info("=" * 70)
                logger.info("   FOR APP STORE REVIEW ONLY")
                logger.info("   All trades are simulated - NO REAL ORDERS PLACED")
                logger.info("   Broker API calls return mock data")
                logger.info("=" * 70)

        # FIX #1: Initialize portfolio state manager for total equity tracking
        try:
            from portfolio_state import get_portfolio_manager
            self.portfolio_manager = get_portfolio_manager()
            logger.info("✅ Portfolio state manager initialized - using total equity for sizing")
        except ImportError:
            logger.warning("⚠️ Portfolio state manager not available - falling back to cash-based sizing")
            self.portfolio_manager = None

        # Initialize Market Readiness Gate for entry quality control
        if MarketReadinessGate is not None:
            try:
                self.market_readiness_gate = MarketReadinessGate()
                logger.info("✅ Market Readiness Gate initialized - entry quality control active")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Market Readiness Gate: {e}")
                self.market_readiness_gate = None
        else:
            self.market_readiness_gate = None
            logger.warning("⚠️ Market Readiness Gate not available - using legacy entry mode")
        
        # Initialize Trade Quality Gate (Layer 2: Better Math Per Trade)
        if TradeQualityGate is not None:
            try:
                self.quality_gate = TradeQualityGate(min_reward_risk=1.5, require_momentum=True)
                logger.info("✅ Trade Quality Gate initialized - R:R filtering active")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize Trade Quality Gate: {e}")
                self.quality_gate = None
        else:
            self.quality_gate = None

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

        # Kraken order cleanup manager (initialized after Kraken connection)
        self.kraken_cleanup = None

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

        # Heartbeat trade state tracking (for deployment verification and health checks)
        self.heartbeat_last_trade_time = 0  # Last heartbeat trade timestamp
        self.heartbeat_trade_count = 0  # Total heartbeat trades executed
        
        # Trade execution tracking (for trade-based cleanup trigger)
        self.trades_since_last_cleanup = 0  # Trades executed since last forced cleanup
        
        # Trade veto tracking for trust layer (log why trades were not executed)
        self.veto_count_session = 0  # Count of vetoed trades this session
        self.last_veto_reason = None  # Last veto reason for display in status banner

        # Position Management State Machine (Feb 15, 2026)
        # Track current state for deterministic position management and proper invariants
        self.position_mgmt_state = PositionManagementState.NORMAL
        self.previous_state = None  # Track previous state for transition logging

        # Initialize advanced trading features placeholder
        # NOTE: Advanced modules will be initialized AFTER first live balance fetch
        # and only if LIVE_CAPITAL_VERIFIED=true is set
        self.advanced_manager = None
        self.rotation_manager = None
        self.pro_mode_enabled = False

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
        
        # Initialize continuous exit enforcer for fail-safe position management
        # This runs independently of the main trading loop to ensure positions
        # are always managed even when main loop encounters errors
        try:
            from continuous_exit_enforcer import get_continuous_exit_enforcer
            logger.info("🛡️ Starting continuous exit enforcer...")
            self.continuous_exit_enforcer = get_continuous_exit_enforcer()
            self.continuous_exit_enforcer.start()
            logger.info("   ✅ Continuous exit enforcer active (checks every 60 seconds)")
        except Exception as e:
            logger.warning(f"⚠️  Could not start continuous exit enforcer: {e}")
            self.continuous_exit_enforcer = None

        try:
            # Lazy imports to avoid circular deps and allow fallback
            # Note: BrokerType and AccountType are now imported at module level
            from broker_manager import (
                BrokerManager, CoinbaseBroker, KrakenBroker,
                OKXBroker, BinanceBroker, AlpacaBroker
            )
            from multi_account_broker_manager import multi_account_broker_manager
            from position_cap_enforcer import PositionCapEnforcer
            from dust_blacklist import get_dust_blacklist
            from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71

            # Initialize multi-account broker manager for user-specific trading
            logger.info("=" * 70)
            logger.info("🌐 MULTI-ACCOUNT TRADING MODE ACTIVATED")
            logger.info("=" * 70)
            logger.info("   Platform account + User accounts trading independently")
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

            # Try to connect Kraken Pro (PRIMARY BROKER) - PLATFORM ACCOUNT
            logger.info("📊 Attempting to connect Kraken Pro (PLATFORM - PRIMARY)...")
            kraken = None  # Initialize to ensure variable exists for exception handler
            try:
                kraken = KrakenBroker(account_type=AccountType.PLATFORM)
                connection_successful = kraken.connect()

                # CRITICAL FIX (Jan 17, 2026): Allow Kraken to start even if connection test fails
                # This prevents a single connection failure from permanently disabling Kraken trading
                # The trading loop will retry connections in the background and self-heal
                # This is similar to how other brokers handle transient connection issues
                if connection_successful:
                    self.broker_manager.add_broker(kraken)
                    # Register in multi_account_manager using proper method to enforce invariant
                    self.multi_account_manager.register_platform_broker_instance(BrokerType.KRAKEN, kraken)
                    connected_brokers.append("Kraken")
                    logger.info("   ✅ Kraken PLATFORM connected")
                    logger.info("   ✅ Kraken registered as PLATFORM broker in multi-account manager")
                    logger.debug(f"   🔍 Kraken broker object: connected={kraken.connected}, account_type={kraken.account_type}")
                    logger.debug(f"   🔍 BrokerType.KRAKEN enum value: {BrokerType.KRAKEN}, type: {type(BrokerType.KRAKEN)}")
                    logger.debug(f"   🔍 platform_brokers dict keys: {list(self.multi_account_manager.platform_brokers.keys())}")
                    logger.debug(f"   🔍 BrokerType.KRAKEN in platform_brokers: {BrokerType.KRAKEN in self.multi_account_manager.platform_brokers}")

                    # LEGACY COPY TRADING CHECK (DEPRECATED - Feb 3, 2026)
                    # NOTE: Copy trading is deprecated. NIJA now uses independent trading.
                    # All accounts (platform + users) trade independently using the same strategy.
                    # This check is kept for backward compatibility but is expected to fail.
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
                            logger.info("   ℹ️  Copy trading not initialized - using independent trading mode")
                    except ImportError:
                        # Expected: Copy trading is deprecated, using independent trading
                        logger.info("   ℹ️  Copy trading not available - all accounts use independent trading")
                    except Exception as copy_err:
                        logger.error(f"   ❌ Unexpected error in copy trading check: {copy_err}")
                        import traceback
                        logger.error(traceback.format_exc())

                    # KRAKEN ORDER CLEANUP: Initialize automatic stale order cleanup
                    # This frees up capital tied in unfilled limit orders
                    try:
                        from bot.kraken_order_cleanup import create_kraken_cleanup
                        self.kraken_cleanup = create_kraken_cleanup(kraken, max_order_age_minutes=5)
                        if self.kraken_cleanup:
                            logger.info("   ✅ Kraken order cleanup initialized (max age: 5 minutes)")
                        else:
                            logger.warning("   ⚠️  Kraken order cleanup not available")
                            self.kraken_cleanup = None
                    except ImportError as import_err:
                        logger.warning(f"   ⚠️  Kraken order cleanup module not available: {import_err}")
                        self.kraken_cleanup = None
                    except Exception as cleanup_err:
                        logger.error(f"   ❌ Kraken order cleanup setup error: {cleanup_err}")
                        self.kraken_cleanup = None
                else:
                    # Connection test failed, but still register broker for background retry
                    # The trading loop will handle the disconnected state and retry automatically
                    logger.warning("   ⚠️  Kraken PLATFORM connection test failed, will retry in background")
                    logger.warning("   📌 Kraken broker initialized - trading loop will attempt reconnection")
                    self._log_broker_independence_message()

                    # Use helper method to register for retry
                    self._register_kraken_for_retry(kraken)

            except Exception as e:
                # CRITICAL FIX (Jan 17, 2026): Handle exceptions consistently with connection failures
                # Even if broker initialization throws an exception, register it for retry if possible
                # This maintains consistent self-healing behavior across all failure types
                if kraken is not None:
                    logger.warning(f"   ⚠️  Kraken PLATFORM initialization error: {e}")
                    logger.warning("   📌 Kraken broker will be registered for background retry")
                    self._log_broker_independence_message()

                    # Use helper method to register for retry
                    self._register_kraken_for_retry(kraken)
                else:
                    # Broker object was never created - can't retry
                    logger.error(f"   ❌ Kraken PLATFORM initialization failed: {e}")
                    logger.error("   ❌ Kraken will not be available for trading")
                    self._log_broker_independence_message()

            # Add delay between broker connections
            time.sleep(2.0)  # Increased from 0.5s to 2.0s

            # COINBASE DISABLED - User requested to disconnect Coinbase (Jan 30, 2026)
            # Kraken is now the exclusive primary broker
            # Coinbase connection code commented out to prevent any Coinbase API usage
            # Original code preserved below for reference if needed in the future
            #
            # # Try to connect Coinbase - PLATFORM ACCOUNT
            # logger.info("📊 Attempting to connect Coinbase Advanced Trade (PLATFORM)...")
            # try:
            #     coinbase = CoinbaseBroker()
            #     if coinbase.connect():
            #         self.broker_manager.add_broker(coinbase)
            #         # Register in multi_account_manager using proper method to enforce invariant
            #         self.multi_account_manager.register_platform_broker_instance(BrokerType.COINBASE, coinbase)
            #         connected_brokers.append("Coinbase")
            #         logger.info("   ✅ Coinbase MASTER connected")
            #         logger.info("   ✅ Coinbase registered as PLATFORM broker in multi-account manager")
            #     else:
            #         logger.warning("   ⚠️  Coinbase MASTER connection failed")
            # except Exception as e:
            #     logger.warning(f"   ⚠️  Coinbase PLATFORM error: {e}")
            
            logger.info("📊 Coinbase connection DISABLED - Kraken is the active broker")
            logger.info("   ℹ️  To re-enable Coinbase, uncomment the connection code in trading_strategy.py")

            # Try to connect OKX - PLATFORM ACCOUNT
            logger.info("📊 Attempting to connect OKX (PLATFORM)...")
            try:
                okx = OKXBroker()
                if okx.connect():
                    self.broker_manager.add_broker(okx)
                    # Register in multi_account_manager using proper method to enforce invariant
                    self.multi_account_manager.register_platform_broker_instance(BrokerType.OKX, okx)
                    connected_brokers.append("OKX")
                    logger.info("   ✅ OKX PLATFORM connected")
                    logger.info("   ✅ OKX registered as PLATFORM broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  OKX PLATFORM connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  OKX PLATFORM error: {e}")

            # Add delay between broker connections
            time.sleep(0.5)

            # Try to connect Binance - PLATFORM ACCOUNT
            logger.info("📊 Attempting to connect Binance (PLATFORM)...")
            try:
                binance = BinanceBroker()
                if binance.connect():
                    self.broker_manager.add_broker(binance)
                    # Register in multi_account_manager using proper method to enforce invariant
                    self.multi_account_manager.register_platform_broker_instance(BrokerType.BINANCE, binance)
                    connected_brokers.append("Binance")
                    logger.info("   ✅ Binance PLATFORM connected")
                    logger.info("   ✅ Binance registered as PLATFORM broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  Binance PLATFORM connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  Binance PLATFORM error: {e}")

            # Add delay between broker connections
            time.sleep(0.5)

            # Try to connect Alpaca (for stocks) - PLATFORM ACCOUNT
            logger.info("📊 Attempting to connect Alpaca (PLATFORM - Paper Trading)...")
            try:
                alpaca = AlpacaBroker()
                if alpaca.connect():
                    self.broker_manager.add_broker(alpaca)
                    # Register in multi_account_manager using proper method to enforce invariant
                    self.multi_account_manager.register_platform_broker_instance(BrokerType.ALPACA, alpaca)
                    connected_brokers.append("Alpaca")
                    logger.info("   ✅ Alpaca PLATFORM connected")
                    logger.info("   ✅ Alpaca registered as PLATFORM broker in multi-account manager")
                else:
                    logger.warning("   ⚠️  Alpaca PLATFORM connection failed")
            except Exception as e:
                logger.warning(f"   ⚠️  Alpaca PLATFORM error: {e}")

            # Add delay before user account connections to ensure platform account
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
                    logger.info(f"✅ PLATFORM ACCOUNT BROKERS: {', '.join(connected_brokers)}")

                    # Note: Coinbase connection disabled (Jan 30, 2026)
                    # Warning messages removed - Kraken is now the exclusive primary broker
                if user_brokers:
                    logger.info(f"👥 USER ACCOUNT BROKERS: {', '.join(user_brokers)}")

                # FIX #1: Calculate LIVE multi-broker capital
                # Total Capital = Coinbase (available, if >= min) + Kraken PLATFORM + Optional user balances

                # Get master balance from broker_manager (sums all connected master brokers)
                platform_balance = self.broker_manager.get_total_balance()

                # Break down master balance by broker for transparency
                coinbase_balance = 0.0
                kraken_balance = 0.0
                other_balance = 0.0

                for broker_type, broker in self.multi_account_manager.platform_brokers.items():
                    if broker and broker.connected:
                        try:
                            balance = broker.get_account_balance()
                            if broker_type == BrokerType.COINBASE:
                                coinbase_balance = balance
                            elif broker_type == BrokerType.KRAKEN:
                                kraken_balance = balance
                            else:
                                other_balance += balance
                        except Exception as e:
                            logger.debug(f"Could not get balance for {broker_type.value}: {e}")

                # Get user balances dynamically from multi_account_manager (for copy-trading transparency)
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

                # Report balances with breakdown
                logger.info("=" * 70)
                logger.info("💰 LIVE MULTI-BROKER CAPITAL BREAKDOWN")
                logger.info("=" * 70)
                if coinbase_balance > 0:
                    logger.info(f"   Coinbase PLATFORM: ${coinbase_balance:,.2f}")
                if kraken_balance > 0:
                    logger.info(f"   Kraken PLATFORM:   ${kraken_balance:,.2f}")
                if other_balance > 0:
                    logger.info(f"   Other Brokers:   ${other_balance:,.2f}")
                logger.info(f"   📊 TOTAL PLATFORM: ${platform_balance:,.2f}")
                if user_total_balance > 0:
                    logger.info(f"   👥 USER ACCOUNTS (INDEPENDENT): ${user_total_balance:,.2f}")
                logger.info("=" * 70)

                # FIX #2: Force capital re-hydration after broker connections
                # MASTER AUTHORITY RULE: Master capital is always authoritative
                # Users are followers, not required for startup
                if platform_balance > 0:
                    # Master is funded - include user balances for total capital
                    total_capital = platform_balance + user_total_balance
                    logger.info(f"   ✅ Capital calculation: Platform (${platform_balance:.2f}) + Users (${user_total_balance:.2f})")
                elif user_total_balance > 0:
                    # Master unfunded but users have capital - allow user-only trading
                    total_capital = user_total_balance
                    logger.info(f"   ✅ Capital calculation: User-only trading (${user_total_balance:.2f})")
                else:
                    # No capital from platform or users - cannot trade
                    logger.error("=" * 70)
                    logger.error("❌ FATAL: No capital detected from any account")
                    logger.error("=" * 70)
                    logger.error(f"   Platform balance: ${platform_balance:.2f}")
                    logger.error(f"   User balance: ${user_total_balance:.2f}")
                    logger.error("")
                    logger.error("   🛑 Bot cannot trade without capital")
                    logger.error("   💵 Fund at least one account to continue")
                    logger.error("=" * 70)
                    raise RuntimeError("No capital detected from master or user accounts")

                # Build list of active exchanges for logging
                active_exchanges = []
                for broker_type, broker in self.multi_account_manager.platform_brokers.items():
                    if broker and broker.connected:
                        active_exchanges.append(broker_type.value)

                # Update capital allocator with live total
                if self.advanced_manager and total_capital > 0:
                    try:
                        self.advanced_manager.capital_allocator.update_total_capital(total_capital)

                        # Update progressive target manager if available
                        if hasattr(self.advanced_manager, 'target_manager') and self.advanced_manager.target_manager:
                            # Progressive targets scale with available capital
                            logger.info(f"   ✅ Progressive targets adjusted for ${total_capital:,.2f} capital")

                        logger.info(f"   ✅ Capital Allocator: ${total_capital:,.2f} (LIVE multi-broker total)")
                        logger.info(f"   ✅ Advanced Trading Manager: Using live capital")
                    except Exception as e:
                        logger.warning(f"   Failed to update capital allocation: {e}")

                # Update portfolio state manager with total equity
                if self.portfolio_manager and total_capital > 0:
                    try:
                        # Initialize/update master portfolio with total capital
                        self.platform_portfolio = self.portfolio_manager.initialize_platform_portfolio(total_capital)
                        logger.info(f"   ✅ Portfolio State Manager updated with ${total_capital:,.2f}")
                    except Exception as e:
                        logger.warning(f"   ⚠️ Could not update portfolio manager: {e}")

                # FIX #2: Explicit confirmation log (CRITICAL - must see this log)
                if total_capital > 0:
                    logger.info("=" * 70)
                    logger.info(f"💰 LIVE CAPITAL SYNC COMPLETE: ${total_capital:.2f}")
                    logger.info(f"   Active exchanges: {', '.join(active_exchanges)}")
                    logger.info("=" * 70)

                # USER BALANCE SNAPSHOT - Visual certainty of all account balances
                # Added per Jan 2026 requirement for absolute visual confirmation
                logger.info("")
                logger.info("=" * 70)
                logger.info("💰 USER BALANCE SNAPSHOT")
                logger.info("=" * 70)

                # Get all balances from multi_account_manager
                all_balances = self.multi_account_manager.get_all_balances()

                # Platform account
                platform_balances = all_balances.get('platform', {})
                platform_total = sum(platform_balances.values())
                logger.info(f"   • Platform: ${platform_total:,.2f}")
                for broker, balance in platform_balances.items():
                    logger.info(f"      - {broker.upper()}: ${balance:,.2f}")

                # User accounts - specifically Daivon and Tania
                users_balances = all_balances.get('users', {})

                # Find and display Daivon's balance
                daivon_total = 0.0
                daivon_brokers = {}
                for user_id, balances in users_balances.items():
                    if 'daivon' in user_id.lower():
                        daivon_total = sum(balances.values())
                        daivon_brokers = balances
                        break

                logger.info(f"   • Daivon: ${daivon_total:,.2f}")
                for broker, balance in daivon_brokers.items():
                    logger.info(f"      - {broker.upper()}: ${balance:,.2f}")

                # Find and display Tania's balance
                tania_total = 0.0
                tania_brokers = {}
                for user_id, balances in users_balances.items():
                    if 'tania' in user_id.lower():
                        tania_total = sum(balances.values())
                        tania_brokers = balances
                        break

                # Display Tania's balance, breaking down by broker type
                # Based on config and README, Tania may have Kraken and/or Alpaca
                tania_kraken = tania_brokers.get('kraken', 0.0)
                tania_alpaca = tania_brokers.get('alpaca', 0.0)
                logger.info(f"   • Tania (Kraken): ${tania_kraken:,.2f}")
                logger.info(f"   • Tania (Alpaca): ${tania_alpaca:,.2f}")

                # Show grand total
                # Note: This should match total_capital (master) + user_total_balance from above
                # This provides a cross-check of the balance calculations
                grand_total = platform_total + daivon_total + tania_total
                logger.info("")
                logger.info(f"   🏦 TOTAL CAPITAL UNDER MANAGEMENT: ${grand_total:,.2f}")
                logger.info("=" * 70)

                # Initialize advanced trading features AFTER first live balance fetch
                # This ensures advanced modules have access to real capital data
                # Gated by LIVE_CAPITAL_VERIFIED environment variable
                logger.info("🔧 Initializing advanced trading modules with live capital...")
                self._init_advanced_features(total_capital)

                # FIX #3: Hard fail if capital below minimum (non-negotiable)
                if total_capital < MINIMUM_TRADING_BALANCE:
                        logger.error("=" * 70)
                        logger.error("❌ FATAL: Capital below minimum — trading disabled")
                        logger.error("=" * 70)
                        logger.error(f"   Current capital: ${total_capital:.2f}")
                        logger.error(f"   Minimum required: ${MINIMUM_TRADING_BALANCE:.2f}")
                        logger.error(f"   Shortfall: ${MINIMUM_TRADING_BALANCE - total_capital:.2f}")
                        logger.error("")
                        logger.error("   🛑 Bot cannot trade with insufficient capital")
                        logger.error("   💵 Fund your account to continue trading")
                        logger.error("=" * 70)
                        raise RuntimeError(f"Capital below minimum — trading disabled (${total_capital:.2f} < ${MINIMUM_TRADING_BALANCE:.2f})")

                # FIX #1: Select primary master broker with Kraken promotion logic
                # CRITICAL: If Coinbase is in exit_only mode or has insufficient balance, promote Kraken to primary
                # Only call this after all brokers are connected to make an informed decision
                self.broker_manager.select_primary_platform_broker()

                # Get the primary broker from broker_manager
                # This is used for platform account trading
                self.broker = self.broker_manager.get_primary_broker()
                if self.broker:
                    # Log the primary master broker with explicit reason if it was switched
                    broker_name = self.broker.broker_type.value.upper()

                    # Check if any other broker is in exit_only mode (indicates a switch happened)
                    exit_only_brokers = []
                    for broker_type, broker in self.multi_account_manager.platform_brokers.items():
                        if broker and broker.connected and broker.exit_only_mode:
                            exit_only_brokers.append(broker_type.value.upper())

                    if exit_only_brokers and broker_name == "KRAKEN":
                        # Kraken was promoted because another broker is exit-only
                        logger.info(f"📌 Active platform broker: {broker_name} ({', '.join(exit_only_brokers)} EXIT-ONLY)")
                    else:
                        logger.info(f"📌 Active platform broker: {broker_name}")

                    # FIX #2: Initialize forced stop-loss with the connected broker
                    if self.forced_stop_loss is None:
                        try:
                            from forced_stop_loss import create_forced_stop_loss
                            self.forced_stop_loss = create_forced_stop_loss(self.broker)
                            logger.info("✅ Forced stop-loss executor initialized with platform broker")
                        except Exception as e:
                            logger.warning(f"⚠️ Could not initialize forced stop-loss: {e}")

                    # FIX #3: Initialize master portfolio state using SUM of ALL master brokers
                    # CRITICAL: Master portfolio must use total_platform_equity = sum(all master brokers)
                    # Do NOT just use primary broker's balance - this ignores capital in other brokers
                    if self.portfolio_manager:
                        try:
                            # Calculate total cash/balance across ALL connected master brokers
                            total_platform_cash = 0.0
                            platform_broker_balances = []

                            for broker_type, broker in self.multi_account_manager.platform_brokers.items():
                                if broker and broker.connected:
                                    try:
                                        broker_balance = broker.get_account_balance()
                                        total_platform_cash += broker_balance
                                        platform_broker_balances.append(f"{broker_type.value}: ${broker_balance:.2f}")
                                        logger.info(f"   💰 Platform broker {broker_type.value}: ${broker_balance:.2f}")
                                    except Exception as broker_err:
                                        logger.warning(f"   ⚠️ Could not get balance from {broker_type.value}: {broker_err}")

                            if total_platform_cash > 0:
                                # Initialize/update master portfolio with TOTAL cash from all brokers
                                # Note: portfolio.total_equity will be cash + position values
                                self.platform_portfolio = self.portfolio_manager.initialize_platform_portfolio(total_platform_cash)
                                logger.info("=" * 70)
                                logger.info("✅ PLATFORM PORTFOLIO INITIALIZED")
                                logger.info("=" * 70)
                                for balance_str in platform_broker_balances:
                                    logger.info(f"   {balance_str}")
                                logger.info(f"   TOTAL PLATFORM CASH: ${total_platform_cash:.2f}")
                                logger.info(f"   TOTAL PLATFORM EQUITY: ${self.platform_portfolio.total_equity:.2f}")
                                logger.info("=" * 70)
                            else:
                                logger.warning("⚠️ No platform broker balances available - portfolio not initialized")
                                self.platform_portfolio = None
                        except Exception as e:
                            logger.warning(f"⚠️ Could not initialize platform portfolio: {e}")
                            self.platform_portfolio = None
                    else:
                        self.platform_portfolio = None
                else:
                    logger.warning("⚠️  No platform broker available")
                    self.platform_portfolio = None
            else:
                logger.error("❌ NO BROKERS CONNECTED - Running in monitor mode")
                self.broker = None

            # Log clear trading status summary
            logger.info("=" * 70)
            logger.info("📊 ACCOUNT TRADING STATUS SUMMARY")
            logger.info("=" * 70)

            # Count active trading accounts
            active_platform_count = 1 if self.broker else 0
            active_user_count = 0

            # Platform account status
            if self.broker:
                logger.info(f"✅ PLATFORM ACCOUNT: TRADING (Broker: {self.broker.broker_type.value.upper()})")
            else:
                logger.info("❌ PLATFORM ACCOUNT: NOT TRADING (No broker connected)")

            # User account status - dynamically load from config
            try:
                from config.user_loader import get_user_config_loader
                user_loader = get_user_config_loader()
                enabled_users = user_loader.get_all_enabled_users()

                if enabled_users:
                    for user in enabled_users:
                        # FIX #1: Check if this is a Kraken user managed by copy trading system
                        is_kraken = user.broker_type.upper() == "KRAKEN"
                        is_copy_trader = getattr(user, 'copy_from_platform', False)
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
            total_active = active_platform_count + active_user_count
            if total_active > 0:
                logger.info(f"🚀 TRADING ACTIVE: {total_active} account(s) ready")
                logger.info("")
                logger.info("Next steps:")
                logger.info("   • Bot will start scanning markets in ~45 seconds")
                logger.info("   • Trades will execute automatically when signals are found")
                logger.info("   • Monitor logs with: tail -f nija.log")
                logger.info("")
                if active_platform_count == 0:
                    logger.info("ℹ️  Platform account not connected")
                    logger.info("")
                    logger.info("💡 RECOMMENDATION: Configure Platform Kraken account")
                    logger.info("")
                    logger.info("   Benefits of adding Platform account:")
                    logger.info("   • Platform trades independently (additional trading capacity)")
                    logger.info("   • Stabilizes system initialization")
                    logger.info("   • Cleaner logs and startup flow")
                    logger.info("")
                    logger.info("   To enable Platform account:")
                    logger.info("   1. Set in your .env file:")
                    logger.info("      KRAKEN_PLATFORM_API_KEY=<your-api-key>")
                    logger.info("      KRAKEN_PLATFORM_API_SECRET=<your-api-secret>")
                    logger.info("")
                    logger.info("   2. Get API credentials at: https://www.kraken.com/u/security/api")
                    logger.info("      (Must use Classic API key, NOT OAuth)")
                    logger.info("")
                    logger.info("   3. Restart the bot")
                    logger.info("")
                    logger.info("   Note: All accounts (Platform + Users) trade independently")
                    logger.info("")
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

            # ============================================================================
            # 🧠 TRUST LAYER - USER STATUS BANNER
            # ============================================================================
            self._display_user_status_banner()

            # ============================================================================
            # 🔍 HEARTBEAT TRADE - Verification Mode
            # ============================================================================
            # Execute a single tiny test trade if HEARTBEAT_TRADE=true
            # This verifies API credentials, trading logic, and order execution
            if os.getenv('HEARTBEAT_TRADE', 'false').lower() in ('true', '1', 'yes'):
                logger.info("=" * 70)
                logger.info("💓 HEARTBEAT TRADE MODE ACTIVATED")
                logger.info("=" * 70)
                logger.info("   This mode will execute ONE tiny test trade")
                logger.info("   Purpose: Verify connectivity and trading functionality")
                logger.info("   Action: Bot will auto-disable after heartbeat completes")
                logger.info("=" * 70)
                self._execute_heartbeat_trade()
                logger.info("=" * 70)
                logger.info("✅ HEARTBEAT TRADE COMPLETE - BOT SHUTTING DOWN")
                logger.info("=" * 70)
                logger.info("   IMPORTANT: Set HEARTBEAT_TRADE=false before restart")
                logger.info("   This prevents heartbeat from executing again")
                logger.info("=" * 70)
                import sys
                sys.exit(0)  # Graceful shutdown after heartbeat

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
                logger.warning("No platform broker available")

            # Initialize position cap enforcer (Maximum 8 positions total across all brokers)
            if self.broker:
                self.enforcer = PositionCapEnforcer(max_positions=8, broker=self.broker)
                
                # Initialize dust blacklist for permanent sub-$1 position exclusion
                try:
                    self.dust_blacklist = get_dust_blacklist()
                    logger.info("🗑️  Dust blacklist initialized for position normalization")
                except Exception as blacklist_err:
                    logger.warning(f"⚠️  Failed to initialize dust blacklist: {blacklist_err}")
                    self.dust_blacklist = None
                
                # Initialize forced cleanup engine for aggressive dust and cap enforcement
                try:
                    from forced_position_cleanup import ForcedPositionCleanup
                    self.forced_cleanup = ForcedPositionCleanup(
                        dust_threshold_usd=1.00,
                        max_positions=8,
                        dry_run=False
                    )
                    logger.info("🧹 Forced position cleanup engine initialized")
                except Exception as cleanup_err:
                    logger.warning(f"⚠️  Failed to initialize forced cleanup: {cleanup_err}")
                    self.forced_cleanup = None

                # Initialize broker failsafes (hard limits and circuit breakers)
                # CRITICAL: Use ONLY master balance, not user balances
                try:
                    from broker_failsafes import create_failsafe_for_broker
                    broker_name = self.broker.broker_type.value if hasattr(self.broker, 'broker_type') else 'coinbase'
                    # ✅ REQUIREMENT 1: Use REAL exchange balance ONLY - No fake $100 fallback
                    if platform_balance <= 0:
                        logger.error(f"❌ Cannot initialize trading: Platform balance is ${platform_balance:.2f}")
                        logger.error("   Fund your account with real capital to enable trading")
                        self.failsafes = None
                    else:
                        account_balance = platform_balance
                        self.failsafes = create_failsafe_for_broker(broker_name, account_balance)
                        logger.info(f"🛡️  Broker failsafes initialized for {broker_name} (Platform balance: ${account_balance:,.2f})")
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

    def adopt_existing_positions(self, broker, broker_name: str = "UNKNOWN", account_id: str = "PLATFORM") -> dict:
        """
        UNIFIED STRATEGY PER ACCOUNT - Core Position Adoption Function
        
        🔒 GUARDRAIL: This function MUST be called on startup for EVERY account.
        It adopts existing open positions from the exchange and immediately
        attaches exit logic (stop-loss, take-profit, trailing stops, time exits).
        
        This enables each account to manage its own positions independently with
        identical exit strategies, regardless of where the position originated.
        
        EXACT FLOW:
        ═══════════════════════════════════════════════════════════════════
        STEP 1: Query Exchange
        ───────────────────────
        - Call broker.get_positions() OR broker.get_open_positions()
        - Fetch ALL open positions currently on the exchange
        - Log count and details of positions found
        
        STEP 2: Wrap in NIJA Model
        ───────────────────────────
        - For each position, extract: symbol, entry_price, quantity, size_usd
        - If entry_price missing: use current_price * 1.01 (safety default)
        - Register in broker.position_tracker using track_entry()
        - This makes positions visible to exit engine
        
        STEP 3: Hand to Exit Engine
        ────────────────────────────
        - Positions are now in position_tracker
        - Next run_cycle() will automatically:
          • Calculate P&L for each position
          • Check stop-loss levels
          • Check take-profit targets
          • Apply trailing stops
          • Monitor time-based exits
        - Exit logic is IDENTICAL for all accounts
        
        STEP 4: Guardrail Verification
        ───────────────────────────────
        - Record adoption in self.position_adoption_status
        - Set adoption_completed flag to prevent silent skips
        - Log adoption summary with position count
        - Return detailed status dict for verification
        ═══════════════════════════════════════════════════════════════════
        
        Args:
            broker: Broker instance to query for positions
            broker_name: Human-readable broker name for logging
            account_id: Account identifier (for multi-account tracking)
            
        Returns:
            dict: Detailed adoption status {
                'success': bool,
                'positions_found': int,
                'positions_adopted': int,
                'adoption_time': str (ISO timestamp),
                'broker_name': str,
                'account_id': str,
                'positions': list of dicts
            }
        """
        if not broker:
            logger.error(f"🔒 GUARDRAIL VIOLATION: Cannot adopt positions - broker is None for {account_id}")
            return {
                'success': False,
                'positions_found': 0,
                'positions_adopted': 0,
                'adoption_time': datetime.now().isoformat(),
                'broker_name': broker_name,
                'account_id': account_id,
                'error': 'Broker is None',
                'positions': []
            }
            
        adoption_start = datetime.now()
        
        try:
            logger.info("")
            logger.info("═" * 70)
            logger.info(f"🔄 ADOPTING EXISTING POSITIONS")
            logger.info("═" * 70)
            logger.info(f"   Account: {account_id}")
            logger.info(f"   Broker: {broker_name.upper()}")
            logger.info(f"   Time: {adoption_start.isoformat()}")
            logger.info("─" * 70)
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 1: Query Exchange for Open Positions
            # ═══════════════════════════════════════════════════════════════
            logger.info("📡 STEP 1/4: Querying exchange for open positions...")
            
            try:
                # Try get_positions first (standard method)
                if hasattr(broker, 'get_positions'):
                    positions = broker.get_positions()
                # Fallback to get_open_positions if available
                elif hasattr(broker, 'get_open_positions'):
                    positions = broker.get_open_positions()
                else:
                    error_msg = f"Broker {broker_name} does not support position queries"
                    logger.error(f"   ❌ {error_msg}")
                    return {
                        'success': False,
                        'positions_found': 0,
                        'positions_adopted': 0,
                        'adoption_time': adoption_start.isoformat(),
                        'broker_name': broker_name,
                        'account_id': account_id,
                        'error': error_msg,
                        'positions': []
                    }
                    
                positions_found = len(positions) if positions else 0
                logger.info(f"   ✅ Exchange query complete: {positions_found} position(s) found")
                
                if not positions:
                    logger.info("   ℹ️  No open positions to adopt")
                    
                    # Check for open orders (pending orders that haven't filled yet)
                    open_orders_count = 0
                    open_orders_info = []
                    try:
                        if hasattr(broker, 'get_open_orders'):
                            open_orders = broker.get_open_orders()
                            if open_orders:
                                open_orders_count = len(open_orders)
                                # Extract key details from orders (show first MAX_DISPLAYED_ORDERS)
                                for order in open_orders[:MAX_DISPLAYED_ORDERS]:
                                    pair = order.get('pair', order.get('symbol', 'UNKNOWN'))
                                    side = order.get('type', order.get('side', 'UNKNOWN'))
                                    price = order.get('price', 0)
                                    age_seconds = order.get('age_seconds', 0)
                                    age_minutes = int(age_seconds / 60) if age_seconds > 0 else 0
                                    origin = order.get('origin', 'UNKNOWN')
                                    
                                    open_orders_info.append({
                                        'pair': pair,
                                        'side': side.upper(),
                                        'price': price,
                                        'age_minutes': age_minutes,
                                        'origin': origin
                                    })
                    except Exception as order_err:
                        logger.debug(f"   Could not check open orders: {order_err}")
                    
                    # Log informative message about open orders
                    if open_orders_count > 0:
                        logger.info(f"   📋 {account_id}: {open_orders_count} open order(s) found but no filled positions yet")
                        logger.info(f"   ⏳ Orders are being monitored and will be adopted upon fill")
                        
                        # Log details of open orders for visibility
                        for i, order_info in enumerate(open_orders_info, 1):
                            logger.info(f"      {i}. {order_info['pair']} {order_info['side']} @ ${order_info['price']:.4f} "
                                      f"(age: {order_info['age_minutes']}m, origin: {order_info['origin']})")
                        
                        if open_orders_count > MAX_DISPLAYED_ORDERS:
                            logger.info(f"      ... and {open_orders_count - MAX_DISPLAYED_ORDERS} more order(s)")
                    
                    logger.info("─" * 70)
                    logger.info("✅ ADOPTION COMPLETE: 0 positions (account has no open positions)")
                    logger.info("═" * 70)
                    logger.info("")
                    return {
                        'success': True,
                        'positions_found': 0,
                        'positions_adopted': 0,
                        'adoption_time': adoption_start.isoformat(),
                        'broker_name': broker_name,
                        'account_id': account_id,
                        'open_orders_count': open_orders_count,
                        'positions': []
                    }
                
            except Exception as fetch_err:
                error_msg = f"Failed to fetch positions: {fetch_err}"
                logger.error(f"   ❌ {error_msg}")
                return {
                    'success': False,
                    'positions_found': 0,
                    'positions_adopted': 0,
                    'adoption_time': adoption_start.isoformat(),
                    'broker_name': broker_name,
                    'account_id': account_id,
                    'error': error_msg,
                    'positions': []
                }
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 2: Wrap Each Position in NIJA's Internal Model
            # ═══════════════════════════════════════════════════════════════
            logger.info("📦 STEP 2/4: Wrapping positions in NIJA internal model...")
            
            adopted_count = 0
            adopted_positions = []
            position_tracker = getattr(broker, 'position_tracker', None)
            
            # 🔒 CAPITAL PROTECTION: position_tracker is MANDATORY - no silent fallback mode
            if not position_tracker:
                logger.error("   ❌ CAPITAL PROTECTION: position_tracker is MANDATORY but not available")
                logger.error("   ❌ Cannot adopt positions without position tracking - FAILING ADOPTION")
                return
            
            for i, pos in enumerate(positions, 1):
                try:
                    symbol = pos.get('symbol', 'UNKNOWN')
                    entry_price = pos.get('entry_price', 0.0)
                    current_price = pos.get('current_price', 0.0)
                    quantity = pos.get('quantity', pos.get('size', 0.0))
                    
                    # Calculate size in USD
                    size_usd = pos.get('size_usd', pos.get('usd_value', 0.0))
                    if size_usd == 0 and current_price > 0 and quantity > 0:
                        size_usd = current_price * quantity
                    
                    # 🔒 CAPITAL PROTECTION: Entry price must NEVER default to 0 - fail adoption if missing
                    # Note: pos.get('entry_price', 0.0) returns 0.0 if key is missing or value is None
                    if entry_price == 0 or entry_price <= 0:
                        logger.error(f"   [{i}/{positions_found}] ❌ CAPITAL PROTECTION: {symbol} has NO ENTRY PRICE")
                        logger.error(f"   ❌ Position adoption FAILED - entry price is MANDATORY")
                        continue  # Skip this position - do not adopt without entry price
                    
                    # Register position in tracker (MANDATORY)
                    success = position_tracker.track_entry(
                        symbol=symbol,
                        entry_price=entry_price,
                        quantity=quantity,
                        size_usd=size_usd,
                        strategy="ADOPTED"
                    )
                    if not success:
                        logger.error(f"   [{i}/{positions_found}] ❌ CAPITAL PROTECTION: {symbol} failed position tracker registration")
                        logger.error(f"   ❌ Position adoption FAILED - tracker registration is MANDATORY")
                        continue
                    
                    # Position successfully adopted
                    adopted_count += 1
                    
                    # Calculate current P&L for logging
                    if current_price > 0 and entry_price > 0:
                        pnl_pct = ((current_price - entry_price) / entry_price) * 100
                    else:
                        pnl_pct = 0.0
                    
                    position_summary = {
                        'symbol': symbol,
                        'entry_price': entry_price,
                        'current_price': current_price,
                        'quantity': quantity,
                        'size_usd': size_usd,
                        'pnl_pct': pnl_pct
                    }
                    adopted_positions.append(position_summary)
                    
                    logger.info(f"   [{i}/{positions_found}] ✅ {symbol}: Entry=${entry_price:.4f}, Current=${current_price:.4f}, P&L={pnl_pct:+.2f}%, Size=${size_usd:.2f}")
                        
                except Exception as pos_err:
                    logger.error(f"   [{i}/{positions_found}] ❌ Failed to adopt position: {pos_err}")
                    continue
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 3: Hand Positions to Exit Engine
            # ═══════════════════════════════════════════════════════════════
            logger.info("🎯 STEP 3/4: Handing positions to exit engine...")
            logger.info(f"   ✅ {adopted_count} position(s) now under exit management")
            logger.info("   ✅ Stop-loss protection: ENABLED")
            logger.info("   ✅ Take-profit targets: ENABLED")
            logger.info("   ✅ Trailing stops: ENABLED")
            logger.info("   ✅ Time-based exits: ENABLED")
            
            # ═══════════════════════════════════════════════════════════════
            # STEP 4: Guardrail Verification & Status Recording
            # ═══════════════════════════════════════════════════════════════
            logger.info("🔒 STEP 4/4: Recording adoption status (guardrail)...")
            
            # Initialize adoption status tracking if not exists
            if not hasattr(self, 'position_adoption_status'):
                self.position_adoption_status = {}
            
            # Record adoption for this account
            adoption_key = f"{account_id}_{broker_name}"
            adoption_status = {
                'success': True,
                'positions_found': positions_found,
                'positions_adopted': adopted_count,
                'adoption_time': adoption_start.isoformat(),
                'broker_name': broker_name,
                'account_id': account_id,
                'positions': adopted_positions,
                'adoption_completed': True  # 🔒 GUARDRAIL FLAG
            }
            self.position_adoption_status[adoption_key] = adoption_status
            
            logger.info(f"   ✅ Adoption recorded for {adoption_key}")
            logger.info("─" * 70)
            
            # 🔒 GUARDRAIL: Log clear summary
            if adopted_count != positions_found:
                logger.warning("⚠️  ADOPTION MISMATCH:")
                logger.warning(f"   Found: {positions_found} positions")
                logger.warning(f"   Adopted: {adopted_count} positions")
                logger.warning(f"   Failed: {positions_found - adopted_count} positions")
            else:
                logger.info("✅ ADOPTION COMPLETE:")
                logger.info(f"   All {adopted_count} position(s) successfully adopted")
            
            logger.info("")
            logger.info("💰 PROFIT REALIZATION ACTIVE:")
            logger.info(f"   Exit logic will run NEXT CYCLE (2.5 min)")
            logger.info(f"   All {adopted_count} position(s) monitored for exits")
            logger.info("═" * 70)
            logger.info("")
            
            return adoption_status
            
        except Exception as e:
            error_msg = f"Critical error during position adoption: {e}"
            logger.error(f"❌ {error_msg}")
            import traceback
            logger.error(traceback.format_exc())
            logger.info("═" * 70)
            logger.info("")
            
            return {
                'success': False,
                'positions_found': 0,
                'positions_adopted': 0,
                'adoption_time': adoption_start.isoformat(),
                'broker_name': broker_name,
                'account_id': account_id,
                'error': error_msg,
                'positions': []
            }

    def verify_position_adoption_status(self, account_id: str, broker_name: str) -> bool:
        """
        🔒 GUARDRAIL: Verify that position adoption completed for an account.
        
        This prevents the silent failure where an account has positions but
        they are not being managed by the exit engine.
        
        MUST be called before allowing trading to proceed.
        
        Args:
            account_id: Account identifier
            broker_name: Broker name
            
        Returns:
            bool: True if adoption completed (or no positions exist), False if silently skipped
        """
        if not hasattr(self, 'position_adoption_status'):
            logger.error("🔒 GUARDRAIL VIOLATION: position_adoption_status not initialized")
            logger.error(f"   Account: {account_id}")
            logger.error(f"   Broker: {broker_name}")
            logger.error("   ❌ adopt_existing_positions() was NEVER called")
            return False
        
        adoption_key = f"{account_id}_{broker_name}"
        
        if adoption_key not in self.position_adoption_status:
            logger.error("🔒 GUARDRAIL VIOLATION: Position adoption was skipped")
            logger.error(f"   Account: {account_id}")
            logger.error(f"   Broker: {broker_name}")
            logger.error(f"   Key: {adoption_key}")
            logger.error("   ❌ adopt_existing_positions() was NOT called for this account")
            logger.error("   ⚠️  Positions may exist but are NOT being managed")
            return False
        
        status = self.position_adoption_status[adoption_key]
        
        if not status.get('adoption_completed', False):
            logger.error("🔒 GUARDRAIL VIOLATION: Adoption incomplete")
            logger.error(f"   Account: {account_id}")
            logger.error(f"   Status: {status}")
            return False
        
        # Log successful verification
        logger.info(f"✅ Position adoption verified for {adoption_key}")
        logger.info(f"   Found: {status['positions_found']} position(s)")
        logger.info(f"   Adopted: {status['positions_adopted']} position(s)")
        logger.info(f"   Time: {status['adoption_time']}")
        
        return True

    def get_adoption_summary(self) -> dict:
        """
        Get summary of position adoption status across all accounts.
        
        Also checks for anomalies like users having positions when platform doesn't.
        
        Returns:
            dict: Summary of adoption status for monitoring/debugging
        """
        if not hasattr(self, 'position_adoption_status'):
            return {
                'initialized': False,
                'accounts': 0,
                'total_positions_found': 0,
                'total_positions_adopted': 0
            }
        
        total_found = 0
        total_adopted = 0
        accounts_with_positions = 0
        
        # Track platform vs user positions for anomaly detection
        platform_positions = 0
        user_positions = 0
        user_accounts_with_positions = []
        
        for key, status in self.position_adoption_status.items():
            positions_count = status.get('positions_found', 0)
            
            if positions_count > 0:
                accounts_with_positions += 1
                
                # Identify if this is platform or user account
                account_id = status.get('account_id', '')
                if account_id.startswith('PLATFORM_'):
                    platform_positions += positions_count
                elif account_id.startswith('USER_'):
                    user_positions += positions_count
                    user_accounts_with_positions.append(account_id)
            
            total_found += positions_count
            total_adopted += status.get('positions_adopted', 0)
        
        # 🔒 ANOMALY DETECTION: Log when users have positions but platform doesn't
        if user_positions > 0 and platform_positions == 0:
            logger.warning("")
            logger.warning("═" * 70)
            logger.warning("⚠️  POSITION DISTRIBUTION ANOMALY DETECTED")
            logger.warning("═" * 70)
            logger.warning(f"   USER accounts have {user_positions} position(s)")
            logger.warning(f"   PLATFORM account has 0 positions")
            logger.warning("")
            logger.warning(f"   User accounts with positions:")
            for user_account in user_accounts_with_positions:
                # Look up status using the account_id (which is already the full key)
                # Find the matching status from position_adoption_status
                user_status = None
                for key, status in self.position_adoption_status.items():
                    if status.get('account_id') == user_account:
                        user_status = status
                        break
                
                if user_status:
                    logger.warning(f"      • {user_account}: {user_status.get('positions_found', 0)} position(s)")
                else:
                    logger.warning(f"      • {user_account}: (status not found)")
            logger.warning("")
            logger.warning("   This is NORMAL if:")
            logger.warning("   - Platform account just started (no trades yet)")
            logger.warning("   - Users opened positions independently")
            logger.warning("   - Platform positions were closed but user positions remain")
            logger.warning("")
            logger.warning("   ✅ Each account manages positions INDEPENDENTLY")
            logger.warning("   ✅ Exit logic active for ALL accounts")
            logger.warning("═" * 70)
            logger.warning("")
        
        return {
            'initialized': True,
            'accounts': len(self.position_adoption_status),
            'accounts_with_positions': accounts_with_positions,
            'total_positions_found': total_found,
            'total_positions_adopted': total_adopted,
            'platform_positions': platform_positions,
            'user_positions': user_positions,
            'anomaly_detected': (user_positions > 0 and platform_positions == 0),
            'details': self.position_adoption_status
        }

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

    def _get_profit_targets_for_capital(self, balance: float) -> list:
        """
        📈 Select profit ladder based on capital tier.
        
        Different capital sizes use different profit targets for optimal risk/reward.
        Larger accounts can afford to wait for bigger wins.
        Smaller accounts need to take profits more aggressively to build capital.
        
        Args:
            balance: Current account balance in USD
            
        Returns:
            list: Profit target ladder (tuples of (pct, reason))
        """
        if balance < 100:
            # MICRO tier: Aggressive profit-taking
            return PROFIT_TARGETS_MICRO
        elif balance < 1000:
            # SMALL tier: Balanced approach
            return PROFIT_TARGETS_SMALL
        elif balance < 10000:
            # MEDIUM tier: Let winners run more
            return PROFIT_TARGETS_MEDIUM
        else:
            # LARGE tier: Maximum profit potential
            return PROFIT_TARGETS_LARGE

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
        # Register in multi_account_manager using proper method to enforce invariant
        self.multi_account_manager.register_platform_broker_instance(BrokerType.KRAKEN, kraken_broker)
        logger.info("   ✅ Kraken registered for background connection retry")

    def _get_total_capital_across_all_accounts(self) -> float:
        """
        Get total capital summed across ALL accounts and brokers.

        ✅ CRITICAL (Jan 22, 2026): Capital must be fetched live and summed dynamically
        - Coinbase Master: fetched live
        - Kraken Master: fetched live
        - Kraken Users: fetched live
        - OKX Master: fetched live (if available)
        - Summed before every allocation cycle

        Returns:
            Total capital in USD across all accounts
        """
        total_capital = 0.0

        try:
            # 1. Sum all PLATFORM broker balances
            if hasattr(self, 'multi_account_manager') and self.multi_account_manager:
                for broker_type, broker in self.multi_account_manager.platform_brokers.items():
                    if broker and broker.connected:
                        try:
                            balance = broker.get_account_balance()
                            total_capital += balance
                            logger.debug(f"   Platform {broker_type.value}: ${balance:.2f}")
                        except Exception as e:
                            logger.warning(f"   ⚠️ Could not fetch {broker_type.value} platform balance: {e}")

                # 2. Sum all USER broker balances
                if self.multi_account_manager.user_brokers:
                    for user_id, user_broker_dict in self.multi_account_manager.user_brokers.items():
                        for broker_type, broker in user_broker_dict.items():
                            if broker and broker.connected:
                                try:
                                    balance = broker.get_account_balance()
                                    total_capital += balance
                                    logger.debug(f"   User {user_id} {broker_type.value}: ${balance:.2f}")
                                except Exception as e:
                                    logger.warning(f"   ⚠️ Could not fetch user {user_id} balance: {e}")

            # Fallback: use broker_manager if multi_account_manager not available
            elif hasattr(self, 'broker_manager') and self.broker_manager:
                total_capital = self.broker_manager.get_total_balance()
                logger.debug(f"   Broker manager total: ${total_capital:.2f}")

            logger.info(f"💰 TOTAL CAPITAL (all accounts): ${total_capital:.2f}")

        except Exception as e:
            logger.error(f"❌ Error calculating total capital: {e}")
            # Return 0 on error - better to halt trading than use stale data
            total_capital = 0.0

        return total_capital

    def _display_user_status_banner(self):
        """
        Display a user status banner with trading capabilities and account information.
        
        This Trust Layer feature provides transparent visibility into:
        - Connected brokers and balances
        - Trading modes (LIVE vs PAPER)
        - Safety settings (LIVE_CAPITAL_VERIFIED, PRO_MODE)
        - Account tier information
        """
        logger.info("")
        logger.info("=" * 70)
        logger.info("🧠 TRUST LAYER - USER STATUS BANNER")
        logger.info("=" * 70)
        
        # Safety settings (enhanced with safety controller)
        if hasattr(self, 'safety') and self.safety:
            # Use new safety controller
            status = self.safety.get_status_summary()
            logger.info("📋 SAFETY SETTINGS:")
            logger.info(f"   • MODE: {status['mode'].upper()}")
            logger.info(f"   • TRADING ALLOWED: {'✅ YES' if status['trading_allowed'] else '❌ NO'}")
            logger.info(f"   • REASON: {status['reason']}")
            logger.info(f"   • EMERGENCY STOP: {'🚨 ACTIVE' if status['emergency_stop_active'] else '✅ INACTIVE'}")
            logger.info(f"   • CREDENTIALS: {'✅ CONFIGURED' if status['credentials_configured'] else '❌ NOT CONFIGURED'}")
        else:
            # Legacy safety checks
            live_capital_verified = os.getenv('LIVE_CAPITAL_VERIFIED', 'false').lower() in ('true', '1', 'yes')
            pro_mode_enabled = os.getenv('PRO_MODE', 'false').lower() in ('true', '1', 'yes')
            heartbeat_enabled = os.getenv('HEARTBEAT_TRADE', 'false').lower() in ('true', '1', 'yes')
            dry_run_mode = os.getenv('DRY_RUN_MODE', 'false').lower() in ('true', '1', 'yes')
            
            logger.info("📋 SAFETY SETTINGS:")
            logger.info(f"   • LIVE_CAPITAL_VERIFIED: {'✅ TRUE' if live_capital_verified else '❌ FALSE'}")
            logger.info(f"   • DRY_RUN_MODE: {'✅ ENABLED' if dry_run_mode else '❌ DISABLED'}")
            logger.info(f"   • PRO_MODE: {'✅ ENABLED' if pro_mode_enabled else '❌ DISABLED'}")
            logger.info(f"   • HEARTBEAT_TRADE: {'✅ ENABLED' if heartbeat_enabled else '❌ DISABLED'}")
        
        # Platform account status
        logger.info("")
        logger.info("📊 PLATFORM ACCOUNT:")
        if self.broker:
            broker_name = self.broker.broker_type.value.upper()
            try:
                balance = self.broker.get_account_balance()
                logger.info(f"   • Broker: {broker_name}")
                logger.info(f"   • Balance: ${balance:,.2f}")
                logger.info(f"   • Status: ✅ CONNECTED")
            except Exception as e:
                logger.info(f"   • Broker: {broker_name}")
                logger.info(f"   • Status: ⚠️  CONNECTION ERROR - {str(e)}")
        else:
            logger.info("   • Status: ❌ NO BROKER CONNECTED")
        
        # User accounts status
        logger.info("")
        logger.info("👥 USER ACCOUNTS:")
        if hasattr(self, 'multi_account_manager') and self.multi_account_manager.user_brokers:
            user_count = 0
            for user_id, user_broker_dict in self.multi_account_manager.user_brokers.items():
                for broker_type, broker in user_broker_dict.items():
                    user_count += 1
                    try:
                        if broker.connected:
                            balance = broker.get_account_balance()
                            logger.info(f"   • {user_id} ({broker_type.value.upper()}): ${balance:,.2f} - ✅ CONNECTED")
                        else:
                            logger.info(f"   • {user_id} ({broker_type.value.upper()}): ❌ NOT CONNECTED")
                    except Exception as e:
                        logger.info(f"   • {user_id} ({broker_type.value.upper()}): ⚠️  ERROR - {str(e)}")
            if user_count == 0:
                logger.info("   • No user accounts configured")
        else:
            logger.info("   • No user accounts configured")
        
        logger.info("=" * 70)
        logger.info("")

    def _execute_heartbeat_trade(self):
        """
        Execute a single tiny test trade to verify connectivity and functionality.
        
        This heartbeat trade:
        - Verifies API credentials are valid
        - Tests order placement and execution
        - Validates trading logic flow
        - Uses minimal position size (typically $5-10)
        
        After execution, the bot will auto-disable to prevent further trading.
        User must set HEARTBEAT_TRADE=false before restarting for normal operation.
        """
        try:
            if not self.broker:
                logger.error("❌ HEARTBEAT FAILED: No broker connected")
                return
            
            logger.info("💓 Executing heartbeat trade verification...")
            logger.info("")
            
            # Get account balance
            try:
                balance = self.broker.get_account_balance()
                logger.info(f"   • Account balance: ${balance:,.2f}")
            except Exception as e:
                logger.error(f"   ❌ Failed to get balance: {e}")
                return
            
            # Verify sufficient balance
            if balance < 10.0:
                logger.error(f"   ❌ Insufficient balance for heartbeat (need $10+, have ${balance:.2f})")
                return
            
            # Get available markets
            try:
                markets = self.broker.get_available_markets()
                if not markets:
                    logger.error("   ❌ No markets available")
                    return
                
                # Select a liquid market for heartbeat (prefer BTC or ETH)
                selected_market = None
                for symbol in ['BTC-USD', 'BTCUSD', 'ETH-USD', 'ETHUSD']:
                    if symbol in markets:
                        selected_market = symbol
                        break
                
                # Fallback to first available market
                if not selected_market and markets:
                    selected_market = markets[0]
                
                if not selected_market:
                    logger.error("   ❌ No suitable market found for heartbeat")
                    return
                
                logger.info(f"   • Selected market: {selected_market}")
                
            except Exception as e:
                logger.error(f"   ❌ Failed to get markets: {e}")
                return
            
            # Calculate heartbeat position size (use minimum $5-10)
            position_size_usd = min(10.0, balance * 0.02)  # 2% of balance, max $10
            logger.info(f"   • Position size: ${position_size_usd:.2f}")
            
            # Execute heartbeat buy order
            logger.info("")
            logger.info("   📍 PLACING HEARTBEAT BUY ORDER...")
            try:
                order_result = self.broker.place_market_order(
                    selected_market,
                    'buy',
                    position_size_usd,
                    size_type='quote'  # Order in USD
                )
                
                if order_result and order_result.get('status') not in ['error', 'unfilled']:
                    logger.info(f"   ✅ Heartbeat buy order placed successfully")
                    logger.info(f"      Order ID: {order_result.get('order_id', 'N/A')}")
                    logger.info(f"      Symbol: {selected_market}")
                    logger.info(f"      Size: ${position_size_usd:.2f}")
                    
                    # Wait a moment for order to fill
                    logger.info("")
                    logger.info("   ⏳ Waiting 5 seconds for order to fill...")
                    time.sleep(5)
                    
                    # Immediately exit the position
                    logger.info("")
                    logger.info("   📍 CLOSING HEARTBEAT POSITION...")
                    try:
                        positions = self.broker.get_positions()
                        for pos in positions:
                            if pos.get('symbol') == selected_market:
                                quantity = pos.get('quantity', 0)
                                if quantity > 0:
                                    sell_result = self.broker.place_market_order(
                                        selected_market,
                                        'sell',
                                        quantity,
                                        size_type='base'  # Order in base currency
                                    )
                                    if sell_result and sell_result.get('status') not in ['error', 'unfilled']:
                                        logger.info(f"   ✅ Heartbeat position closed successfully")
                                        logger.info("")
                                        logger.info("💓 HEARTBEAT TRADE VERIFICATION: ✅ SUCCESS")
                                    else:
                                        logger.warning(f"   ⚠️  Heartbeat sell failed: {sell_result.get('error', 'Unknown error')}")
                                    break
                        else:
                            logger.warning("   ⚠️  No position found to close (may have been filled partially)")
                            logger.info("")
                            logger.info("💓 HEARTBEAT TRADE VERIFICATION: ⚠️  PARTIAL SUCCESS")
                    except Exception as e:
                        logger.error(f"   ❌ Failed to close heartbeat position: {e}")
                        logger.info("")
                        logger.info("💓 HEARTBEAT TRADE VERIFICATION: ⚠️  PARTIAL SUCCESS")
                else:
                    error_msg = order_result.get('error', 'Unknown error') if order_result else 'Order failed'
                    logger.error(f"   ❌ Heartbeat buy order failed: {error_msg}")
                    logger.info("")
                    logger.info("💓 HEARTBEAT TRADE VERIFICATION: ❌ FAILED")
                    
            except Exception as e:
                logger.error(f"   ❌ Exception during heartbeat trade: {e}")
                logger.info("")
                logger.info("💓 HEARTBEAT TRADE VERIFICATION: ❌ FAILED")
                
        except Exception as e:
            logger.error(f"❌ HEARTBEAT FATAL ERROR: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def get_last_evaluated_trade(self) -> dict:
        """
        Get the last evaluated trade for UI display.
        
        Returns:
            dict: Last evaluated trade information including:
                - timestamp: When the trade was evaluated
                - symbol: Trading pair
                - signal: 'BUY' or 'SELL'
                - action: 'executed', 'vetoed', or 'evaluated'
                - veto_reasons: List of veto reasons if blocked
                - entry_price: Proposed entry price
                - position_size: Proposed position size in USD
                - broker: Broker name
                - confidence: Signal confidence (0.0-1.0)
                - rsi_9: RSI 9-period value
                - rsi_14: RSI 14-period value
        """
        return self.last_evaluated_trade.copy()

    def _update_last_evaluated_trade(self, symbol: str, signal: str, action: str,
                                     veto_reasons: list = None, entry_price: float = None,
                                     position_size: float = None, broker: str = None,
                                     confidence: float = None, rsi_9: float = None,
                                     rsi_14: float = None):
        """
        Update the last evaluated trade information.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USD')
            signal: 'BUY' or 'SELL'
            action: 'executed', 'vetoed', or 'evaluated'
            veto_reasons: List of reasons if trade was vetoed
            entry_price: Proposed entry price
            position_size: Proposed position size in USD
            broker: Broker name (e.g., 'KRAKEN')
            confidence: Signal confidence (0.0-1.0)
            rsi_9: RSI 9-period value
            rsi_14: RSI 14-period value
        """
        self.last_evaluated_trade = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'signal': signal,
            'action': action,
            'veto_reasons': veto_reasons or [],
            'entry_price': entry_price,
            'position_size': position_size,
            'broker': broker,
            'confidence': confidence,
            'rsi_9': rsi_9,
            'rsi_14': rsi_14
        }

    def _init_advanced_features(self, total_capital: float = 0.0):
        """Initialize progressive targets, exchange risk profiles, and capital allocation.

        This is optional and will gracefully degrade if modules are not available.

        Also initializes PRO MODE rotation manager if enabled.

        CRITICAL: This method is gated by LIVE_CAPITAL_VERIFIED environment variable.
        Advanced modules are only initialized if LIVE_CAPITAL_VERIFIED=true is set.

        Args:
            total_capital: Live capital from broker connections (default: 0.0)
        """
        # CRITICAL SAFETY: Check LIVE_CAPITAL_VERIFIED first
        # This is the MASTER safety switch that must be explicitly enabled
        # to allow advanced trading features with real capital.
        live_capital_verified_str = os.getenv('LIVE_CAPITAL_VERIFIED', 'false').lower().strip()
        live_capital_verified = live_capital_verified_str in ['true', '1', 'yes', 'enabled']

        if not live_capital_verified:
            logger.info("=" * 70)
            logger.info("🔒 LIVE CAPITAL VERIFIED: FALSE")
            logger.info("   Advanced trading modules initialization SKIPPED")
            logger.info("   To enable advanced features, set LIVE_CAPITAL_VERIFIED=true in .env")
            logger.info("=" * 70)
            self.rotation_manager = None
            self.pro_mode_enabled = False
            self.advanced_manager = None
            return

        logger.info("=" * 70)
        logger.info("🔓 LIVE CAPITAL VERIFIED: TRUE")
        logger.info("   Initializing advanced trading modules...")
        logger.info("=" * 70)

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

            # FIX #1: Use live capital passed from broker connections
            # This is the actual balance fetched from Coinbase, Kraken, and other brokers
            # Only fall back to environment variable if no capital was passed
            if total_capital > 0.01:  # Use small threshold to avoid floating-point precision issues
                # Use live capital from broker connections (PREFERRED)
                initial_capital = total_capital
                logger.info(f"ℹ️ Using LIVE capital from broker connections: ${initial_capital:.2f}")
            else:
                # Fallback: Try to get from environment variable
                initial_capital_str = os.getenv('INITIAL_CAPITAL', 'auto').strip().upper()

                # Support "auto" and "LIVE" as aliases for automatic balance detection
                if initial_capital_str in ('AUTO', 'LIVE'):
                    # Can't initialize without capital - skip initialization
                    logger.warning(f"⚠️ INITIAL_CAPITAL={initial_capital_str.lower()} but no live capital available")
                    logger.warning(f"   Advanced manager will not be initialized")
                    self.advanced_manager = None
                    return
                else:
                    # Try to parse as numeric value
                    try:
                        initial_capital = float(initial_capital_str)
                        if initial_capital <= 0:
                            logger.warning(f"⚠️ INITIAL_CAPITAL not set or zero, cannot initialize advanced manager")
                            self.advanced_manager = None
                            return
                        else:
                            logger.info(f"ℹ️ Using INITIAL_CAPITAL from environment: ${initial_capital:.2f}")
                    except (ValueError, TypeError):
                        logger.warning(f"⚠️ Invalid INITIAL_CAPITAL={initial_capital_str}, cannot initialize advanced manager")
                        self.advanced_manager = None
                        return

            allocation_strategy = os.getenv('ALLOCATION_STRATEGY', 'conservative')

            # Initialize advanced manager with live capital from broker connections
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
            veto_reason = "Broker not available"
            logger.info(f"🚫 TRADE VETO: {veto_reason}")
            self.veto_count_session += 1
            self.last_veto_reason = veto_reason
            return False, veto_reason

        broker_name = self._get_broker_name(broker)

        if not broker.connected:
            veto_reason = f"{broker_name.upper()} not connected"
            logger.info(f"🚫 TRADE VETO: {veto_reason}")
            logger.debug(f"   _is_broker_eligible_for_entry: {broker_name} not connected")
            self.veto_count_session += 1
            self.last_veto_reason = veto_reason
            return False, veto_reason

        # Check if broker is in EXIT_ONLY mode
        if hasattr(broker, 'exit_only_mode') and broker.exit_only_mode:
            veto_reason = f"{broker_name.upper()} in EXIT-ONLY mode"
            logger.info(f"🚫 TRADE VETO: {veto_reason}")
            logger.debug(f"   _is_broker_eligible_for_entry: {broker_name} in EXIT_ONLY mode")
            self.veto_count_session += 1
            self.last_veto_reason = veto_reason
            return False, veto_reason

        # Check if account balance meets minimum threshold
        # CRITICAL FIX (Jan 28, 2026): Use timeout to prevent hanging on slow balance fetches
        # Timeout configured to accommodate Kraken's API timeout (30s) plus network overhead (15s)
        try:
            # Call get_account_balance with timeout to prevent indefinite hanging
            # Uses BALANCE_FETCH_TIMEOUT (45s = 30s Kraken API timeout + 15s network/serialization buffer)
            # Note: Kraken makes 2 API calls (Balance + TradeBalance) with 1s minimum interval between calls
            balance_result = call_with_timeout(broker.get_account_balance, timeout_seconds=BALANCE_FETCH_TIMEOUT)

            # Check if timeout or error occurred
            # call_with_timeout returns (value, None) on success, (None, error) on failure
            if balance_result[1] is not None:  # Error from call_with_timeout
                error_msg = balance_result[1]
                logger.warning(f"   _is_broker_eligible_for_entry: {broker_name} balance fetch timed out or failed: {error_msg}")

                # CRITICAL FIX (Jan 27, 2026): More permissive cached balance fallback
                # When API is slow/timing out, we should still try to trade using cached balance
                # Previously was too conservative - would reject broker if no timestamp
                if hasattr(broker, '_last_known_balance') and broker._last_known_balance is not None:
                    cached_balance = broker._last_known_balance

                    # Check if cached balance has a timestamp (for staleness check)
                    cache_is_fresh = False
                    if hasattr(broker, '_balance_last_updated') and broker._balance_last_updated is not None:
                        balance_age_seconds = time.time() - broker._balance_last_updated
                        cache_is_fresh = balance_age_seconds <= CACHED_BALANCE_MAX_AGE_SECONDS
                        if not cache_is_fresh:
                            logger.warning(f"   ⚠️  Cached balance for {broker_name} is stale ({balance_age_seconds:.0f}s old > {CACHED_BALANCE_MAX_AGE_SECONDS}s max)")
                    else:
                        # CRITICAL FIX (Jan 27, 2026): Conditional cache usage when no timestamp
                        # If broker doesn't track timestamp, we can't verify age
                        # SAFE APPROACH: Only use cache if broker object was created recently (this session)
                        # This prevents trading with very stale data from previous sessions

                        # Check if broker has a 'connected_at' or similar timestamp
                        broker_session_age = None
                        if hasattr(broker, 'connected_at'):
                            broker_session_age = time.time() - broker.connected_at
                        elif hasattr(broker, 'created_at'):
                            broker_session_age = time.time() - broker.created_at

                        # Only use untimestamped cache if broker was connected/created in last 10 minutes
                        # This ensures cache is from current trading session, not stale from previous run
                        if broker_session_age is not None and broker_session_age <= 600:  # 10 minutes
                            cache_is_fresh = True
                            logger.info(f"   ℹ️  {broker_name} cached balance has no timestamp, but broker connected {broker_session_age:.0f}s ago - using cache")
                        else:
                            # No timestamp and no session age - too risky to use
                            cache_is_fresh = False
                            logger.warning(f"   ⚠️  {broker_name} cached balance has no timestamp and no session age - rejecting for safety")

                    if cache_is_fresh:
                        logger.info(f"   ✅ Using cached balance for {broker_name}: ${cached_balance:.2f}")
                        broker_type = broker.broker_type if hasattr(broker, 'broker_type') else None
                        min_balance = BROKER_MIN_BALANCE.get(broker_type, MIN_BALANCE_TO_TRADE_USD)

                        if cached_balance >= min_balance:
                            return True, f"Eligible (cached ${cached_balance:.2f} >= ${min_balance:.2f} min)"
                        else:
                            veto_reason = f"{broker_name.upper()} cached balance ${cached_balance:.2f} < ${min_balance:.2f} minimum"
                            logger.info(f"🚫 TRADE VETO: {veto_reason}")
                            self.veto_count_session += 1
                            self.last_veto_reason = veto_reason
                            return False, veto_reason

                veto_reason = f"{broker_name.upper()} balance fetch failed: timeout or error"
                logger.info(f"🚫 TRADE VETO: {veto_reason}")
                self.veto_count_session += 1
                self.last_veto_reason = veto_reason
                return False, veto_reason

            balance = balance_result[0] if balance_result[0] is not None else 0.0
            
            # 🔒 CAPITAL PROTECTION: Validate broker data completeness before allowing entries
            # Balance of 0.0 could indicate incomplete/missing data
            if balance == 0.0:
                veto_reason = f"{broker_name.upper()} broker data incomplete: balance is 0.0"
                logger.warning(f"🚫 CAPITAL PROTECTION: {veto_reason}")
                logger.info(f"🚫 TRADE VETO: {veto_reason}")
                self.veto_count_session += 1
                self.last_veto_reason = veto_reason
                return False, veto_reason
            
            broker_type = broker.broker_type if hasattr(broker, 'broker_type') else None
            min_balance = BROKER_MIN_BALANCE.get(broker_type, MIN_BALANCE_TO_TRADE_USD)

            logger.debug(f"   _is_broker_eligible_for_entry: {broker_name} balance=${balance:.2f}, min=${min_balance:.2f}")

            if balance < min_balance:
                veto_reason = f"{broker_name.upper()} balance ${balance:.2f} < ${min_balance:.2f} minimum"
                logger.info(f"🚫 TRADE VETO: {veto_reason}")
                self.veto_count_session += 1
                self.last_veto_reason = veto_reason
                return False, veto_reason

            # 🔒 CAPITAL PROTECTION: Final check - ensure broker has position_tracker
            if not hasattr(broker, 'position_tracker') or broker.position_tracker is None:
                veto_reason = f"{broker_name.upper()} broker data incomplete: no position_tracker"
                logger.error(f"🚫 CAPITAL PROTECTION: {veto_reason}")
                logger.info(f"🚫 TRADE VETO: {veto_reason}")
                self.veto_count_session += 1
                self.last_veto_reason = veto_reason
                return False, veto_reason

            return True, f"Eligible (${balance:.2f} >= ${min_balance:.2f} min)"
        except Exception as e:
            veto_reason = f"{broker_name.upper()} balance check failed: {e}"
            logger.warning(f"   _is_broker_eligible_for_entry: {broker_name} balance check exception: {e}")
            logger.info(f"🚫 TRADE VETO: {veto_reason}")
            self.veto_count_session += 1
            self.last_veto_reason = veto_reason
            return False, veto_reason

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

        # CRITICAL FIX (Jan 24, 2026): Add debug logging to diagnose broker selection issues
        logger.debug(f"_select_entry_broker called with {len(all_brokers)} brokers: {[bt.value for bt in all_brokers.keys()]}")

        # Check each broker in priority order
        for broker_type in ENTRY_BROKER_PRIORITY:
            broker = all_brokers.get(broker_type)

            if not broker:
                eligibility_status[broker_type.value] = "Not configured"
                logger.debug(f"   {broker_type.value}: Not in all_brokers dict")
                continue

            is_eligible, reason = self._is_broker_eligible_for_entry(broker)
            eligibility_status[broker_type.value] = reason
            logger.debug(f"   {broker_type.value}: is_eligible={is_eligible}, reason={reason}")

            if is_eligible:
                broker_name = self._get_broker_name(broker)
                logger.info(f"✅ Selected {broker_name.upper()} for entry (priority: {ENTRY_BROKER_PRIORITY.index(broker_type) + 1})")
                return broker, broker_name, eligibility_status

        # No eligible broker found
        logger.debug(f"_select_entry_broker: No eligible broker found. Status: {eligibility_status}")
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

        # Kraken with small balance: Use -0.8% primary stop (conservative)
        if 'kraken' in broker_name and account_balance < 100:
            # For small Kraken balances, use conservative -0.8% primary stop
            # This accounts for spread (0.1%) + fees (0.36%) + slippage (0.1%) + buffer (0.24%)
            primary_stop = STOP_LOSS_PRIMARY_KRAKEN  # -0.8%
            description = f"Kraken small balance (${account_balance:.2f}): Primary -0.8%, Micro -2.0%, Failsafe -5.0%"

        # Kraken with larger balance: Can use tighter stop
        elif 'kraken' in broker_name:
            # For larger Kraken balances, use -0.5% minimum (tighter for better capital preservation)
            primary_stop = STOP_LOSS_PRIMARY_KRAKEN_MIN  # -0.5%
            description = f"Kraken (${account_balance:.2f}): Primary -0.5%, Micro -2.0%, Failsafe -5.0%"

        # 🚨 COINBASE TIGHTENED STOP-LOSS (Jan 28, 2026)
        # Improved to -1.0% max for better capital preservation and risk/reward ratio
        elif 'coinbase' in broker_name:
            primary_stop = STOP_LOSS_PRIMARY_COINBASE  # -1.0% (improved from -1.25%)
            description = f"COINBASE (${account_balance:.2f}): Primary -1.0%, Micro -2.0%, Failsafe -5.0%"

        # Other exchanges: Use -1.0% primary stop (conservative default)
        else:
            # Higher fees require wider stop-loss
            primary_stop = -0.010  # -1.0% for other exchanges
            description = f"{broker_name.upper()} (${account_balance:.2f}): Primary -1.0%, Micro -2.0%, Failsafe -5.0%"

        return (
            primary_stop,           # Tier 1: Primary trading stop
            STOP_LOSS_MICRO,        # Tier 2: Emergency micro-stop (-1%)
            STOP_LOSS_EMERGENCY,    # Tier 3: Catastrophic failsafe (-5%)
            description
        )

    def _display_user_status_banner(self, broker=None):
        """
        Display user status banner with trading status and account info.
        
        Shows:
        - Current capital/balance
        - Active positions count
        - Trading status (active/vetoed)
        - Last veto reason (if any)
        - Heartbeat status (if enabled)
        
        Args:
            broker: Optional broker instance to get current status from
        """
        logger.info("=" * 70)
        logger.info("📊 USER STATUS BANNER")
        logger.info("=" * 70)
        
        # Display capital information
        try:
            if broker and broker.connected:
                balance = broker.get_account_balance()
                broker_name = self._get_broker_name(broker)
                logger.info(f"   💰 {broker_name.upper()} Balance: ${balance:,.2f}")
                
                # Get active positions count
                try:
                    positions = broker.get_positions()
                    active_count = len(positions) if positions else 0
                    logger.info(f"   📈 Active Positions: {active_count}")
                except Exception as e:
                    logger.debug(f"   Could not get positions: {e}")
            else:
                logger.info("   ⚠️  No broker connected")
        except Exception as e:
            logger.debug(f"   Could not get balance: {e}")
        
        # Display trading status
        if self.last_veto_reason:
            logger.info(f"   🚫 Trading Status: VETOED")
            logger.info(f"   📋 Last Veto Reason: {self.last_veto_reason}")
            logger.info(f"   📊 Vetoed Trades (Session): {self.veto_count_session}")
        else:
            logger.info(f"   ✅ Trading Status: ACTIVE")
        
        # Display heartbeat status if enabled
        if HEARTBEAT_TRADE_ENABLED:
            if self.heartbeat_last_trade_time > 0:
                time_since_heartbeat = int(time.time() - self.heartbeat_last_trade_time)
                logger.info(f"   ❤️  Heartbeat: Last trade {time_since_heartbeat}s ago ({self.heartbeat_trade_count} total)")
            else:
                logger.info(f"   ❤️  Heartbeat: ENABLED (awaiting first trade)")
        
        logger.info("=" * 70)
    
    def _execute_heartbeat_trade(self, broker=None):
        """
        Execute a tiny heartbeat trade to verify exchange connectivity.
        
        Heartbeat trades are minimal size ($5.50) test trades that:
        - Verify API credentials are working
        - Confirm order execution is functional
        - Monitor exchange connectivity health
        
        Only executes if:
        - HEARTBEAT_TRADE_ENABLED is true
        - Sufficient time has passed since last heartbeat (HEARTBEAT_TRADE_INTERVAL_SECONDS)
        - Broker is connected and has sufficient balance
        
        Args:
            broker: Broker instance to execute heartbeat trade on
            
        Returns:
            bool: True if heartbeat trade was executed, False otherwise
        """
        if not HEARTBEAT_TRADE_ENABLED:
            return False
        
        current_time = time.time()
        
        # Check if enough time has passed since last heartbeat
        if self.heartbeat_last_trade_time > 0:
            time_since_last = current_time - self.heartbeat_last_trade_time
            if time_since_last < HEARTBEAT_TRADE_INTERVAL_SECONDS:
                return False
        
        # Verify broker is available
        if not broker or not broker.connected:
            logger.debug("   Heartbeat trade skipped: no broker connected")
            return False
        
        broker_name = self._get_broker_name(broker)
        
        try:
            # Get account balance to verify we can trade
            balance = broker.get_account_balance()
            if balance < HEARTBEAT_TRADE_SIZE_USD:
                logger.warning(f"   ❤️  Heartbeat trade skipped: ${balance:.2f} < ${HEARTBEAT_TRADE_SIZE_USD:.2f} minimum")
                return False
            
            # Get available markets
            markets = broker.get_available_markets()
            if not markets:
                logger.warning("   ❤️  Heartbeat trade skipped: no markets available")
                return False
            
            # Select a liquid, low-volatility market for heartbeat (prefer BTC-USD or ETH-USD)
            # Try multiple symbol format variations to match broker's format
            preferred_symbols = ['BTC-USD', 'BTCUSD', 'ETH-USD', 'ETHUSD', 'BTC/USD', 'ETH/USD']
            heartbeat_symbol = None
            
            for symbol in preferred_symbols:
                # Try exact match first
                if symbol in markets:
                    heartbeat_symbol = symbol
                    break
                # Try format variations
                symbol_dash = symbol.replace('/', '-')
                symbol_slash = symbol.replace('-', '/')
                if symbol_dash in markets:
                    heartbeat_symbol = symbol_dash
                    break
                if symbol_slash in markets:
                    heartbeat_symbol = symbol_slash
                    break
            
            # Fallback to first available market
            if not heartbeat_symbol and markets:
                heartbeat_symbol = markets[0]
            
            if not heartbeat_symbol:
                logger.warning("   ❤️  Heartbeat trade skipped: no suitable symbol found")
                return False
            
            # Execute tiny market buy order
            logger.info("=" * 70)
            logger.info(f"❤️  HEARTBEAT TRADE EXECUTION")
            logger.info("=" * 70)
            logger.info(f"   Symbol: {heartbeat_symbol}")
            logger.info(f"   Size: ${HEARTBEAT_TRADE_SIZE_USD:.2f}")
            logger.info(f"   Broker: {broker_name.upper()}")
            logger.info(f"   Purpose: Verify connectivity & order execution")
            
            # Place market buy order
            # Note: size_type='quote' means size is in USD, not base currency
            # If broker doesn't support size_type parameter, this will use the size as base currency amount
            try:
                order_result = broker.place_market_order(
                    symbol=heartbeat_symbol,
                    side='buy',
                    size=HEARTBEAT_TRADE_SIZE_USD,
                    size_type='quote'  # USD amount, not base currency amount
                )
            except TypeError:
                # Broker doesn't support size_type parameter - fallback to positional args
                logger.debug(f"   Broker {broker_name} doesn't support size_type parameter, using default")
                order_result = broker.place_market_order(
                    symbol=heartbeat_symbol,
                    side='buy',
                    size=HEARTBEAT_TRADE_SIZE_USD
                )
            
            if order_result and order_result.get('status') in ['filled', 'open', 'pending']:
                self.heartbeat_last_trade_time = current_time
                self.heartbeat_trade_count += 1
                
                logger.info(f"   ✅ Heartbeat trade #{self.heartbeat_trade_count} EXECUTED")
                logger.info(f"   Order ID: {order_result.get('order_id', 'N/A')}")
                logger.info(f"   Status: {order_result.get('status', 'unknown')}")
                logger.info("=" * 70)
                
                return True
            else:
                logger.warning(f"   ❌ Heartbeat trade failed: {order_result}")
                logger.info("=" * 70)
                return False
                
        except Exception as e:
            logger.error(f"   ❤️  Heartbeat trade error: {e}")
            logger.error(f"   {traceback.format_exc()}")
            return False

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
                      Default False for PLATFORM accounts (full strategy execution)

        Steps:
        1. Enforce position cap (auto-sell excess if needed)
        2. [PLATFORM ONLY] Scan markets for opportunities
        3. [PLATFORM ONLY] Execute entry logic / [USER] Execute position exits only
        4. Update trailing stops and take profits
        5. Log cycle summary
        """
        # Use provided broker or fall back to self.broker (thread-safe approach)
        active_broker = broker if broker is not None else self.broker

        # CRITICAL SAFETY CHECK: Verify trading is allowed before ANY operations
        if self.safety:
            trading_allowed, reason = self.safety.is_trading_allowed()
            if not trading_allowed and not user_mode:
                # Trading not allowed - only execute if this is a position management cycle
                logger.warning("=" * 70)
                logger.warning("🛑 TRADING NOT ALLOWED")
                logger.warning("=" * 70)
                logger.warning(f"   Reason: {reason}")
                logger.warning("   Mode: Position management only (exits/stops)")
                logger.warning("   No new entries will be executed")
                logger.warning("=" * 70)
                # Allow position management (exits/stops) but block new entries
                user_mode = True  # Force user mode to disable new entries

        # Log mode for clarity
        mode_label = "USER (position management only)" if user_mode else "MASTER (full strategy)"
        logger.info(f"🔄 Trading cycle mode: {mode_label}")
        
        # Display user status banner (trust layer feature)
        self._display_user_status_banner(broker=active_broker)
        
        # Execute heartbeat trade if enabled and due
        if not user_mode:  # Only execute heartbeat in MASTER mode
            heartbeat_executed = self._execute_heartbeat_trade(broker=active_broker)
            if heartbeat_executed:
                logger.info("   ❤️  Heartbeat trade executed - connectivity verified")
        
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
            
            # 🧹 FORCED CLEANUP: Run aggressive dust cleanup and retroactive cap enforcement
            # This runs periodically to clean up:
            # 1. Dust positions < $1 USD
            # 2. Excess positions over hard cap (retroactive enforcement)
            # Runs across ALL accounts (platform + users)
            run_startup_cleanup = hasattr(self, 'cycle_count') and self.cycle_count == 0
            run_periodic_cleanup = hasattr(self, 'cycle_count') and self.cycle_count > 0 and (self.cycle_count % FORCED_CLEANUP_INTERVAL == 0)
            
            # Optional trade-based trigger: Cleanup after N trades
            run_trade_based_cleanup = False
            if FORCED_CLEANUP_AFTER_N_TRADES and hasattr(self, 'trades_since_last_cleanup'):
                run_trade_based_cleanup = self.trades_since_last_cleanup >= FORCED_CLEANUP_AFTER_N_TRADES
            
            if hasattr(self, 'forced_cleanup') and self.forced_cleanup and (run_startup_cleanup or run_periodic_cleanup or run_trade_based_cleanup):
                # Determine cleanup reason for logging
                if run_startup_cleanup:
                    cleanup_reason = "STARTUP"
                elif run_trade_based_cleanup:
                    cleanup_reason = f"TRADE-BASED ({self.trades_since_last_cleanup} trades executed)"
                else:
                    cleanup_reason = f"PERIODIC (cycle {self.cycle_count})"
                
                logger.warning(f"")
                logger.warning(f"🧹 FORCED CLEANUP TRIGGERED: {cleanup_reason}")
                logger.warning(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                logger.warning(f"   Interval: Every {FORCED_CLEANUP_INTERVAL} cycles (~{FORCED_CLEANUP_INTERVAL * 2.5:.0f} minutes)")
                if FORCED_CLEANUP_AFTER_N_TRADES:
                    logger.warning(f"   Trade trigger: After {FORCED_CLEANUP_AFTER_N_TRADES} trades (current: {self.trades_since_last_cleanup})")
                try:
                    if hasattr(self, 'multi_account_manager') and self.multi_account_manager:
                        # Run cleanup across all accounts
                        summary = self.forced_cleanup.cleanup_all_accounts(self.multi_account_manager, is_startup=run_startup_cleanup)
                        logger.warning(f"   ✅ Cleanup complete: Reduced positions by {summary['reduction']}")
                    else:
                        # Single account mode - just cleanup platform
                        logger.info(f"   Running single-account cleanup...")
                        if active_broker:
                            result = self.forced_cleanup.cleanup_single_account(active_broker, "platform", is_startup=run_startup_cleanup)
                            logger.warning(f"   ✅ Cleanup complete: {result['initial_positions']} → {result['final_positions']}")
                    
                    # Reset trade counter after cleanup
                    if hasattr(self, 'trades_since_last_cleanup'):
                        self.trades_since_last_cleanup = 0
                        
                except Exception as cleanup_err:
                    logger.error(f"   ❌ Forced cleanup failed: {cleanup_err}")
                    import traceback
                    logger.error(traceback.format_exc())
                logger.warning(f"")

            # CRITICAL FIX (Jan 24, 2026): Get positions from ALL connected brokers, not just active_broker
            # This ensures positions on all exchanges are monitored for stop-loss, profit-taking, etc.
            # Previously, switching active_broker to Kraken would cause Coinbase positions to be ignored
            current_positions = []
            positions_by_broker = {}  # Track which broker each position belongs to

            # CRITICAL FIX (Jan 24, 2026): Periodic position tracker sync
            # Sync every 10 cycles (~25 minutes) to proactively clear phantom positions
            # Phantom positions = tracked internally but don't exist on exchange
            # This prevents accumulation of stale position data
            sync_interval = 10
            if hasattr(self, 'cycle_count') and self.cycle_count > 0 and (self.cycle_count % sync_interval == 0):
                if active_broker and hasattr(active_broker, 'position_tracker') and active_broker.position_tracker:
                    try:
                        broker_positions = active_broker.get_positions()
                        removed = active_broker.position_tracker.sync_with_broker(broker_positions)
                        if removed > 0:
                            logger.info(f"🔄 Periodic sync: Cleared {removed} phantom position(s) from tracker")
                    except Exception as sync_err:
                        logger.debug(f"   ⚠️ Periodic position sync failed: {sync_err}")

            if hasattr(self, 'multi_account_manager') and self.multi_account_manager:
                # Get positions from all connected platform brokers (user brokers tracked separately)
                logger.info("ℹ️  User positions excluded from platform caps")
                for broker_type, broker in self.multi_account_manager.platform_brokers.items():
                    if broker and broker.connected:
                        try:
                            broker_positions = broker.get_positions()
                            if broker_positions:
                                # Tag each position with its broker for later management
                                for pos in broker_positions:
                                    pos['_broker'] = broker  # Store broker reference
                                    pos['_broker_type'] = broker_type  # Store broker type for logging
                                current_positions.extend(broker_positions)
                                # Safely get broker name (handles both enum and string)
                                broker_name = broker_type.value.upper() if hasattr(broker_type, 'value') else str(broker_type).upper()
                                positions_by_broker[broker_name] = len(broker_positions)
                                logger.debug(f"   Fetched {len(broker_positions)} positions from {broker_name}")
                        except Exception as e:
                            # Safely get broker name for error logging
                            broker_name = broker_type.value.upper() if hasattr(broker_type, 'value') else str(broker_type).upper()
                            logger.warning(f"   ⚠️ Could not fetch positions from {broker_name}: {e}")

                # Log positions by broker for visibility
                if positions_by_broker:
                    logger.info(f"   📊 Positions by broker: {', '.join([f'{name}={count}' for name, count in positions_by_broker.items()])}")
            elif active_broker:
                # Fallback: If multi_account_manager not available, use active_broker
                current_positions = active_broker.get_positions() if active_broker else []
                logger.debug(f"   Fetched {len(current_positions)} positions from active broker (fallback mode)")
            else:
                logger.warning("   ⚠️ No brokers available to fetch positions from")
                current_positions = []

            # CRITICAL FIX: Filter out unsellable positions (dust, unsupported symbols)
            # These positions can't be traded so they shouldn't count toward position cap
            # This prevents dust positions from blocking new entries
            # Note: After timeout expires (24h), positions will be included and retry attempted
            if current_positions and hasattr(self, 'unsellable_positions'):
                tradable_positions = []
                for pos in current_positions:
                    symbol = pos.get('symbol')
                    if symbol and symbol in self.unsellable_positions:
                        # Check if the unsellable timeout is still active (position still marked as unsellable)
                        # When timeout expires, position will be included in count and exit will be retried
                        # (in case position grew above minimum or API error was temporary)
                        marked_time = self.unsellable_positions[symbol]
                        time_since_marked = time.time() - marked_time
                        if time_since_marked < self.unsellable_retry_timeout:
                            # Timeout hasn't passed yet - exclude from count
                            logger.debug(f"   Excluding {symbol} from position count (marked unsellable {time_since_marked/3600:.1f}h ago)")
                            continue  # Skip this position - don't count it
                    tradable_positions.append(pos)

                # Log if we filtered any positions
                filtered_count = len(current_positions) - len(tradable_positions)
                if filtered_count > 0:
                    logger.info(f"   ℹ️  Filtered {filtered_count} unsellable position(s) from count (dust or unsupported)")

                current_positions = tradable_positions

            # POSITION NORMALIZATION: Filter out permanently blacklisted dust positions
            # These are positions < $1 USD that have been permanently excluded
            if current_positions and hasattr(self, 'dust_blacklist') and self.dust_blacklist:
                non_blacklisted_positions = []
                blacklisted_count = 0
                
                for pos in current_positions:
                    symbol = pos.get('symbol')
                    if symbol and self.dust_blacklist.is_blacklisted(symbol):
                        blacklisted_count += 1
                        logger.debug(f"   ⛔ Excluding blacklisted position: {symbol}")
                        continue
                    non_blacklisted_positions.append(pos)
                
                if blacklisted_count > 0:
                    logger.info(f"   🗑️  Filtered {blacklisted_count} blacklisted position(s) from count (permanent dust exclusion)")
                
                current_positions = non_blacklisted_positions

            stop_entries_file = os.path.join(os.path.dirname(__file__), '..', 'STOP_ALL_ENTRIES.conf')
            entries_blocked = os.path.exists(stop_entries_file)

            # Determine if we're in management-only mode
            managing_only = user_mode or entries_blocked or len(current_positions) >= MAX_POSITIONS_ALLOWED

            if entries_blocked:
                logger.error("🛑 ALL NEW ENTRIES BLOCKED: STOP_ALL_ENTRIES.conf is active")
                logger.info("   Exiting positions only (no new buys)")
            elif len(current_positions) >= MAX_POSITIONS_ALLOWED:
                logger.warning(f"🛑 ENTRY BLOCKED: Position cap reached ({len(current_positions)}/{MAX_POSITIONS_ALLOWED})")
                logger.info("   Closing positions only until below cap")
            else:
                logger.info(f"✅ Position cap OK ({len(current_positions)}/{MAX_POSITIONS_ALLOWED}) - entries enabled")

            # 🎯 EXPLICIT PROFIT REALIZATION ACTIVE PROOF
            if managing_only and len(current_positions) > 0:
                logger.info("=" * 70)
                logger.info("💰 PROFIT REALIZATION ACTIVE (Management Mode)")
                logger.info("=" * 70)
                logger.info(f"   📊 {len(current_positions)} open position(s) being monitored")
                logger.info("   ✅ Independent exit logic ENABLED:")
                logger.info("      • Take-profit targets")
                logger.info("      • Trailing stops")
                logger.info("      • Stop-loss protection")
                logger.info("      • Time-based exits")
                logger.info("   🔄 Profit realization runs EVERY cycle (2.5 min)")
                logger.info("   🚫 New entries: BLOCKED")
                logger.info("=" * 70)

            # CRITICAL FIX: Always try to manage positions BEFORE checking strategy
            # This ensures exit logic runs even if apex strategy fails to load
            # Previous bug: Early return here would skip ALL position management
            
            # Get account balance for position sizing
            # NOTE: We no longer return early here - we'll check later for new entries only
            if not active_broker:
                logger.warning("⚠️ No active broker - cannot manage positions")
                logger.info("📡 Monitor mode (no broker connection)")
                return
            
            if not self.apex:
                logger.warning("⚠️ Strategy not loaded - position management may be limited")
                logger.warning("   Will attempt to close positions but cannot open new ones")

            # FIX #1: Update portfolio state from broker data
            # Get detailed balance including crypto holdings
            # PRO MODE: Also calculate total capital (free balance + position values)
            if hasattr(active_broker, 'get_account_balance_detailed'):
                balance_data = active_broker.get_account_balance_detailed()
            else:
                balance_data = {'trading_balance': active_broker.get_account_balance()}
            account_balance = balance_data.get('trading_balance', 0.0)

            # ✅ CRITICAL FIX (Jan 22, 2026): Update capital dynamically BEFORE allocation
            # Capital must be fetched live, not stuck at initialization value
            # This ensures failsafes and allocators use current real balance

            # Get total capital across ALL accounts (master + users)
            total_capital = self._get_total_capital_across_all_accounts()

            # Update failsafes with TOTAL capital (all accounts summed)
            # Note: Failsafes protect the ENTIRE trading operation, not just one broker
            if hasattr(self, 'failsafes') and self.failsafes:
                try:
                    self.failsafes.update_account_balance(total_capital)
                except Exception as e:
                    logger.warning(f"⚠️ Could not update failsafe balance: {e}")

            # Update capital allocator with TOTAL capital (all accounts summed)
            if hasattr(self, 'advanced_manager') and self.advanced_manager:
                try:
                    if hasattr(self.advanced_manager, 'capital_allocator'):
                        self.advanced_manager.capital_allocator.update_total_capital(total_capital)
                except Exception as e:
                    logger.warning(f"⚠️ Could not update capital allocator balance: {e}")

            # Update portfolio state (if available)
            if self.portfolio_manager and hasattr(self, 'platform_portfolio') and self.platform_portfolio:
                try:
                    # Update portfolio from current broker state
                    self.portfolio_manager.update_portfolio_from_broker(
                        portfolio=self.platform_portfolio,
                        available_cash=account_balance,
                        positions=current_positions
                    )

                    # Log portfolio summary
                    summary = self.platform_portfolio.get_summary()
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

            # KRAKEN ORDER CLEANUP: Cancel stale limit orders to free capital
            # This runs every cycle if Kraken cleanup is available and broker is Kraken
            if self.kraken_cleanup and hasattr(active_broker, 'broker_type') and active_broker.broker_type == BrokerType.KRAKEN:
                try:
                    # Only run cleanup if enough time has passed (default: 5 minutes)
                    # Use slightly longer interval than order age to give orders time to fill
                    if self.kraken_cleanup.should_run_cleanup(min_interval_minutes=6):
                        logger.info("")
                        cancelled_count, capital_freed = self.kraken_cleanup.cleanup_stale_orders(dry_run=False)
                        if cancelled_count > 0:
                            logger.info(f"   🧹 Kraken cleanup: Freed ${capital_freed:.2f} by cancelling {cancelled_count} stale order(s)")
                            # Update balance after freeing capital
                            try:
                                old_balance = account_balance
                                new_balance = active_broker.get_account_balance()
                                # Always update balance regardless of whether it increased
                                account_balance = new_balance
                                if new_balance > old_balance:
                                    logger.info(f"   💰 Balance increased: ${old_balance:.2f} → ${new_balance:.2f} (+${new_balance - old_balance:.2f})")
                            except Exception as balance_err:
                                logger.debug(f"   Could not refresh balance: {balance_err}")
                except Exception as cleanup_err:
                    logger.warning(f"⚠️ Kraken order cleanup error: {cleanup_err}")

            # Small delay after balance check to avoid rapid-fire API calls
            time.sleep(0.5)

            # CRITICAL FIX: Wrap position management in try-except to ensure it ALWAYS runs
            # Previous bug: Any exception in position fetching would skip ALL exit logic
            # New behavior: Exit logic attempts to run even if other parts fail
            try:
                # STEP 1: Manage existing positions (check for exits/profit taking)
                logger.info(f"📊 Managing {len(current_positions)} open position(s)...")

                # LOG POSITION PROFIT STATUS FOR VISIBILITY (Jan 26, 2026)
                if current_positions:
                    try:
                        # Get current prices for all open positions
                        current_prices_dict = {}
                        for pos in current_positions:
                            try:
                                symbol = pos.get('symbol')
                                if symbol:
                                    # Fetch current price from broker
                                    candles = active_broker.get_market_data(symbol, limit=1)
                                    if candles and len(candles) > 0:
                                        current_prices_dict[symbol] = candles[-1]['close']
                            except Exception as price_err:
                                logger.debug(f"Could not fetch price for {pos.get('symbol')}: {price_err}")

                        # Log position profit status summary
                        if hasattr(self, 'execution_engine') and self.execution_engine:
                            self.execution_engine.log_position_profit_status(current_prices_dict)
                    except Exception as log_err:
                        logger.debug(f"Could not log position profit status during position monitoring: {log_err}")

                # NOTE (Jan 24, 2026): Stop-loss tiers are now calculated PER-POSITION based on each position's broker
                # This ensures correct stop-loss thresholds for positions on different exchanges (Kraken vs Coinbase)
                # See line ~2169 where position_primary_stop, position_micro_stop are calculated for each position
                # using self._get_stop_loss_tier(position_broker, position_broker_balance)

                # STATE MACHINE: Calculate current state based on position count and forced unwind status
                # Position cap set to 8 maximum concurrent positions
                positions_over_cap = len(current_positions) - MAX_POSITIONS_ALLOWED
                
                # INVARIANT VALIDATION: Ensure position count and excess are valid
                assert len(current_positions) >= 0, f"INVARIANT VIOLATION: Position count is negative: {len(current_positions)}"
                assert positions_over_cap >= -MAX_POSITIONS_ALLOWED, f"INVARIANT VIOLATION: Invalid excess calculation: {positions_over_cap}"
                
                # CRITICAL: Check for forced unwind mode (per-user emergency exit)
                # When enabled, ALL positions are closed immediately regardless of P&L
                forced_unwind_active = False
                if hasattr(self, 'continuous_exit_enforcer') and self.continuous_exit_enforcer:
                    # Get user_id from broker (if available)
                    user_id = getattr(active_broker, 'user_id', 'platform')
                    forced_unwind_active = self.continuous_exit_enforcer.is_forced_unwind_active(user_id)
                
                # Determine new state based on current conditions
                if forced_unwind_active:
                    new_state = PositionManagementState.FORCED_UNWIND
                elif positions_over_cap > 0:
                    new_state = PositionManagementState.DRAIN
                else:
                    new_state = PositionManagementState.NORMAL
                
                # INVARIANT VALIDATION: Validate state invariants before proceeding
                StateInvariantValidator.validate_state_invariants(
                    new_state, 
                    len(current_positions), 
                    positions_over_cap, 
                    MAX_POSITIONS_ALLOWED
                )
                
                # STATE TRANSITION LOGGING: Log state changes explicitly
                if new_state != self.position_mgmt_state:
                    old_state_name = self.position_mgmt_state.value.upper()
                    new_state_name = new_state.value.upper()
                    
                    # Validate transition is allowed
                    if StateInvariantValidator.validate_state_transition(
                        self.position_mgmt_state, new_state, len(current_positions), positions_over_cap
                    ):
                        logger.warning("=" * 80)
                        logger.warning(f"🔄 STATE TRANSITION: {old_state_name} → {new_state_name}")
                        logger.warning("=" * 80)
                        logger.warning(f"   Positions: {len(current_positions)}/{MAX_POSITIONS_ALLOWED}")
                        logger.warning(f"   Excess: {positions_over_cap}")
                        logger.warning(f"   Forced Unwind: {forced_unwind_active}")
                        logger.warning("=" * 80)
                        
                        self.previous_state = self.position_mgmt_state
                        self.position_mgmt_state = new_state
                    else:
                        logger.error(f"INVALID STATE TRANSITION BLOCKED: {old_state_name} → {new_state_name}")
                        # Keep current state if transition is invalid
                        new_state = self.position_mgmt_state
                
                # CRITICAL FIX: Identify ALL positions that need to exit first
                # Then sell them ALL concurrently, not one at a time
                positions_to_exit = []
                
                # FORCED UNWIND MODE: Close all positions immediately
                if new_state == PositionManagementState.FORCED_UNWIND:
                    logger.error("=" * 80)
                    logger.error("🚨 FORCED UNWIND MODE ACTIVE")
                    logger.error("=" * 80)
                    if hasattr(self, 'continuous_exit_enforcer') and self.continuous_exit_enforcer:
                        user_id = getattr(active_broker, 'user_id', 'platform')
                        logger.error(f"   User: {user_id}")
                    logger.error(f"   Positions: {len(current_positions)}")
                    logger.error("   ALL positions will be closed immediately")
                    logger.error("   Bypassing all normal trading filters")
                    logger.error("=" * 80)
                    
                    logger.warning("🚨 FORCED UNWIND: Adding all positions to exit queue")
                    for position in current_positions:
                        symbol = position.get('symbol')
                        quantity = position.get('quantity', 0)
                        position_broker = position.get('_broker', active_broker)
                        position_broker_type = position.get('_broker_type')
                        broker_label = position_broker_type.value.upper() if (position_broker_type and hasattr(position_broker_type, 'value')) else "UNKNOWN"
                        
                        if symbol and quantity > 0:
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': 'FORCED UNWIND (emergency consolidation)',
                                'broker': position_broker,
                                'broker_label': broker_label,
                                'force_liquidate': True  # Bypass all filters
                            })
                    
                    logger.warning(f"🚨 FORCED UNWIND: {len(positions_to_exit)} positions queued for immediate exit")
                    # Skip normal position analysis - just close everything
                
                # DRAIN MODE: Over position cap, actively draining excess positions
                elif new_state == PositionManagementState.DRAIN:
                    logger.info("=" * 70)
                    logger.info("🔥 DRAIN MODE ACTIVE")
                    logger.info("=" * 70)
                    logger.info(f"   📊 Excess positions: {positions_over_cap}")
                    logger.info(f"   🎯 Strategy: Rank by PnL, age, and size")
                    logger.info(f"   🔄 Drain rate: 1-{min(positions_over_cap, 3)} positions per cycle")
                    logger.info(f"   🚫 New entries: BLOCKED until under {MAX_POSITIONS_ALLOWED} positions")
                    logger.info(f"   💡 Goal: Gradually free capital and reduce risk")
                    logger.info("=" * 70)
                    for idx, position in enumerate(current_positions):
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

                            # CRITICAL FIX (Jan 24, 2026): Use the correct broker for this position
                            # Each position is tagged with its broker when fetched from multi_account_manager
                            position_broker = position.get('_broker', active_broker)
                            position_broker_type = position.get('_broker_type')
                            # Safely get broker label (handles both enum and string)
                            broker_label = position_broker_type.value.upper() if (position_broker_type and hasattr(position_broker_type, 'value')) else "UNKNOWN"

                            logger.info(f"   Analyzing {symbol} on {broker_label}...")

                            # Get current price from the position's broker
                            current_price = position_broker.get_current_price(symbol)
                            if not current_price or current_price == 0:
                                logger.warning(f"   ⚠️ Could not get price for {symbol} from {broker_label}")
                                continue

                            # Get position value
                            quantity = position.get('quantity', 0)
                            position_value = current_price * quantity

                            logger.info(f"   {symbol} ({broker_label}): {quantity:.8f} @ ${current_price:.2f} = ${position_value:.2f}")

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
                                    'reason': f'Small position cleanup (${position_value:.2f})',
                                    'broker': position_broker,
                                    'broker_label': broker_label
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
                                                    # Increment trade counter for trade-based cleanup trigger
                                                    if hasattr(self, 'trades_since_last_cleanup'):
                                                        self.trades_since_last_cleanup += 1
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
                                                        # Increment trade counter for trade-based cleanup trigger
                                                        if hasattr(self, 'trades_since_last_cleanup'):
                                                            self.trades_since_last_cleanup += 1
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
                                                    # Increment trade counter for trade-based cleanup trigger
                                                    if hasattr(self, 'trades_since_last_cleanup'):
                                                        self.trades_since_last_cleanup += 1
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
                                                        # Increment trade counter for trade-based cleanup trigger
                                                        if hasattr(self, 'trades_since_last_cleanup'):
                                                            self.trades_since_last_cleanup += 1
                                                    else:
                                                        error_msg = result.get('error', 'Unknown error') if result else 'No response'
                                                        logger.error(f"   ❌ MICRO-STOP FAILED: {error_msg}")
                                                except Exception as sell_err:
                                                    logger.error(f"   ❌ MICRO-STOP EXCEPTION: {sell_err}")

                                            continue

                                        # 🚨 COINBASE LOCKDOWN (Jan 2026) - EXIT ANY LOSS IMMEDIATELY
                                        # Coinbase has been holding losing trades - enforce ZERO TOLERANCE for losses
                                        # Exit ANY position showing ANY loss on Coinbase (no waiting period)
                                        if pnl_percent < 0 and 'coinbase' in broker_label.lower():
                                            logger.warning(f"   🚨 COINBASE LOCKDOWN: {symbol} showing loss at {pnl_percent*100:.2f}%")
                                            logger.warning(f"   💥 ZERO TOLERANCE MODE - exiting Coinbase loss immediately!")
                                            positions_to_exit.append({
                                                'symbol': symbol,
                                                'quantity': quantity,
                                                'reason': f'Coinbase lockdown: ANY loss exit ({pnl_percent*100:.2f}%)',
                                                'broker': position_broker,
                                                'broker_label': broker_label
                                            })
                                            continue

                                        # ✅ LOSING TRADES: 15-MINUTE MAXIMUM HOLD TIME (for non-Coinbase)
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
                                                    'reason': f'Losing trade time exit (held {position_age_minutes:.1f}min at {pnl_percent*100:.2f}%)',
                                                    'broker': position_broker,
                                                    'broker_label': broker_label
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
                                                    'reason': f'Losing position without time tracking (P&L: {pnl_percent*100:.2f}%)',
                                                    'broker': position_broker,
                                                    'broker_label': broker_label
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

                                        # 💎 PROFIT PROTECTION: Never Break Even, Never Loss (Jan 23, 2026)
                                        # NIJA is for PROFIT ONLY - exit when profit decreases more than 0.5%
                                        # Fixed 0.5% pullback allowed - exit when profit drops 0.5%+ from previous check
                                        # Learning and adjusting: allow small pullback but exit on larger decrease
                                        if PROFIT_PROTECTION_ENABLED:
                                            previous_profit_pct = pnl_data.get('previous_profit_pct', 0.0)

                                            # Determine minimum profit threshold based on broker
                                            try:
                                                broker_type = getattr(active_broker, 'broker_type', None)
                                            except AttributeError:
                                                broker_type = None

                                            protection_min_profit = PROFIT_PROTECTION_MIN_PROFIT_KRAKEN if broker_type == BrokerType.KRAKEN else PROFIT_PROTECTION_MIN_PROFIT

                                            # RULE 1: Exit on Profit Decrease > 0.5%
                                            # If position is profitable AND profit decreases by MORE than 0.5%, exit
                                            # Hold up to 0.5% pullback, exit when it exceeds
                                            # Example: 3.0% → 2.9% (0.1% decrease) = HOLD
                                            #          3.0% → 2.5% (0.5% decrease) = HOLD
                                            #          3.0% → 2.49% (0.51% decrease) = EXIT
                                            #          3.0% → 2.4% (0.6% decrease) = EXIT
                                            if pnl_percent >= protection_min_profit and previous_profit_pct >= protection_min_profit:
                                                # Calculate decrease from previous profit
                                                profit_decrease = previous_profit_pct - pnl_percent

                                                # Exit if decrease EXCEEDS 0.5% (> not >=)
                                                if profit_decrease > PROFIT_PROTECTION_PULLBACK_FIXED:
                                                    logger.warning(f"   💎 PROFIT PROTECTION: {symbol} profit pullback exceeded")
                                                    logger.warning(f"      Previous profit: {previous_profit_pct*100:+.2f}% → Current: {pnl_percent*100:+.2f}%")
                                                    logger.warning(f"      Pullback: {profit_decrease*100:.3f}% (max allowed: 0.5%)")
                                                    logger.warning(f"   🔒 TAKING PROFIT NOW - PULLBACK EXCEEDS 0.5%!")
                                                    positions_to_exit.append({
                                                        'symbol': symbol,
                                                        'quantity': quantity,
                                                        'reason': f'Profit pullback {profit_decrease*100:.2f}% exceeded 0.5% limit',
                                                        'broker': position_broker,
                                                        'broker_label': broker_label
                                                    })
                                                    continue

                                                # Log protection status
                                                if profit_decrease > 0:
                                                    cushion = (PROFIT_PROTECTION_PULLBACK_FIXED - profit_decrease) * 100
                                                    logger.debug(f"   💎 Profit pullback within limit: {symbol} at {pnl_percent*100:+.2f}% (pullback: {profit_decrease*100:.3f}%, cushion: {cushion:.3f}%)")
                                                else:
                                                    logger.debug(f"   💎 Profit increasing: {symbol} at {pnl_percent*100:+.2f}% (previous: {previous_profit_pct*100:+.2f}%)")

                                            # RULE 2: Never Break Even Protection
                                            # If position was profitable above minimum threshold and current profit approaches breakeven, exit immediately
                                            if PROFIT_PROTECTION_NEVER_BREAKEVEN and previous_profit_pct >= protection_min_profit and pnl_percent < protection_min_profit:
                                                logger.warning(f"   🚫 NEVER BREAK EVEN: {symbol} approaching breakeven after being profitable")
                                                logger.warning(f"      Previous profit: {previous_profit_pct*100:+.2f}% → Current: {pnl_percent*100:+.2f}%")
                                                logger.warning(f"   🔒 EXITING NOW - NIJA NEVER BREAKS EVEN!")
                                                positions_to_exit.append({
                                                    'symbol': symbol,
                                                    'quantity': quantity,
                                                    'reason': f'Never break even: was {previous_profit_pct*100:+.2f}%, now {pnl_percent*100:+.2f}%',
                                                    'broker': position_broker,
                                                    'broker_label': broker_label
                                                })
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
                                                    # 💰 EXPLICIT PROFIT REALIZATION LOG (Management Mode)
                                                    if managing_only:
                                                        logger.info(f"   💰 PROFIT REALIZATION (MANAGEMENT MODE): {symbol}")
                                                        logger.info(f"      Current P&L: +{pnl_percent*100:.2f}%")
                                                        logger.info(f"      Profit target: +{target_pct*100:.2f}%")
                                                        logger.info(f"      Reason: {reason}")
                                                        logger.info(f"      🔥 Proof: Realizing profit even with new entries BLOCKED")
                                                    else:
                                                        logger.info(f"   🎯 PROFIT TARGET HIT: {symbol} at +{pnl_percent*100:.2f}% (target: +{target_pct*100}%, min threshold: +{min_threshold*100:.1f}%)")
                                                    positions_to_exit.append({
                                                        'symbol': symbol,
                                                        'quantity': quantity,
                                                        'reason': f'{reason} hit (actual: +{pnl_percent*100:.2f}%)',
                                                        'broker': position_broker,
                                                        'broker_label': broker_label
                                                    })
                                                    break  # Exit the for loop, continue to next position
                                                else:
                                                    logger.info(f"   ⚠️ Target {target_pct*100}% hit but profit {pnl_percent*100:.2f}% < minimum threshold {min_threshold*100:.1f}% - holding")
                                        else:
                                            # No profit target hit, check stop loss (LEGACY FALLBACK)
                                            # CRITICAL FIX (Jan 19, 2026): Stop-loss checks happen BEFORE time-based exits
                                            # This ensures losing trades get stopped out immediately, not held for hours

                                            # CATASTROPHIC STOP LOSS: Force exit at -5% or worse (ABSOLUTE FAILSAFE)
                                            if pnl_percent <= STOP_LOSS_EMERGENCY:
                                                if managing_only:
                                                    logger.warning(f"   💰 LOSS PROTECTION (MANAGEMENT MODE): {symbol}")
                                                    logger.warning(f"      Current P&L: {pnl_percent*100:.2f}%")
                                                    logger.warning(f"      Catastrophic stop: {STOP_LOSS_EMERGENCY*100:.0f}%")
                                                    logger.warning(f"      🔥 Proof: Protecting capital even with new entries BLOCKED")
                                                else:
                                                    logger.warning(f"   🛡️ CATASTROPHIC PROTECTIVE EXIT: {symbol} at {pnl_percent*100:.2f}% (threshold: {STOP_LOSS_EMERGENCY*100:.0f}%)")
                                                logger.warning(f"   💥 PROTECTIVE ACTION: Exiting to prevent severe capital loss")
                                                positions_to_exit.append({
                                                    'symbol': symbol,
                                                    'quantity': quantity,
                                                    'reason': f'Catastrophic protective exit at {STOP_LOSS_EMERGENCY*100:.0f}% (actual: {pnl_percent*100:.2f}%)',
                                                    'broker': position_broker,
                                                    'broker_label': broker_label
                                                })
                                            # STANDARD STOP LOSS: Normal stop-loss threshold
                                            # CRITICAL FIX (Feb 3, 2026): Changed AND to OR - was preventing stops from triggering!
                                            # BUG: "pnl <= -2% AND pnl <= -0.25%" requires BOTH conditions (creates restrictive zone)
                                            #      Only triggers if pnl <= -2% (stricter threshold), making -0.25% floor meaningless
                                            # FIX: "pnl <= -1.5% OR pnl <= -0.05%" triggers when EITHER condition met (proper stop logic)
                                            #      Now triggers at WHICHEVER threshold is hit first
                                            # This was causing 80%+ of stop losses to FAIL and positions to keep losing
                                            elif pnl_percent <= STOP_LOSS_THRESHOLD or pnl_percent <= MIN_LOSS_FLOOR:
                                                if managing_only:
                                                    logger.warning(f"   💰 LOSS PROTECTION (MANAGEMENT MODE): {symbol}")
                                                    logger.warning(f"      Current P&L: {pnl_percent*100:.2f}%")
                                                    logger.warning(f"      Stop-loss threshold: {STOP_LOSS_THRESHOLD*100:.2f}%")
                                                    logger.warning(f"      🔥 Proof: Cutting losses even with new entries BLOCKED")
                                                else:
                                                    logger.warning(f"   🛑 PROTECTIVE STOP-LOSS HIT: {symbol} at {pnl_percent*100:.2f}% (threshold: {STOP_LOSS_THRESHOLD*100:.2f}%)")
                                                # PROFITABILITY GUARD: Verify this is actually a losing position
                                                if pnl_percent >= 0:
                                                    logger.error(f"   ❌ PROFITABILITY GUARD: Attempted to stop-loss a WINNING position at +{pnl_percent*100:.2f}%!")
                                                    logger.error(f"   🛡️ GUARD BLOCKED: Not exiting profitable position")
                                                else:
                                                    positions_to_exit.append({
                                                        'symbol': symbol,
                                                        'quantity': quantity,
                                                        'reason': f'Protective stop-loss at {STOP_LOSS_THRESHOLD*100:.2f}% (actual: {pnl_percent*100:.2f}%)',
                                                        'broker': position_broker,
                                                        'broker_label': broker_label
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
                                                    'reason': f'Zombie position exit (stuck at {pnl_percent:+.2f}% for {position_age_hours:.1f}h - likely masked loser)',
                                                    'broker': position_broker,
                                                    'broker_label': broker_label
                                                })
                                            else:
                                                # Position has entry price but not at any exit threshold
                                                # CRITICAL FIX (Jan 19, 2026): Add time-based exits AFTER stop-loss checks
                                                # Railway Golden Rule #5: Stop-loss > time exit (always)
                                                # Only check time-based exits if stop-loss didn't trigger

                                                # Common holding message (avoid duplication)
                                                holding_msg = f"   📊 Holding {symbol}: P&L {pnl_percent:+.2f}% (no exit threshold reached)"

                                                if entry_time_available:
                                                    # 🚨 COINBASE LOCKDOWN (Jan 2026) - FORCE EXIT AFTER 30 MINUTES
                                                    # Coinbase positions MUST exit within 30 minutes (even if profitable)
                                                    # This prevents holding positions too long and missing exit opportunities
                                                    if 'coinbase' in broker_label.lower():
                                                        position_age_minutes = position_age_hours * MINUTES_PER_HOUR
                                                        if position_age_minutes >= COINBASE_MAX_HOLD_MINUTES:
                                                            logger.warning(f"   🚨 COINBASE TIME LOCKDOWN: {symbol} held {position_age_minutes:.1f} min (max: {COINBASE_MAX_HOLD_MINUTES})")
                                                            logger.warning(f"   💥 Force exiting to lock in current P&L: {pnl_percent*100:+.2f}%")
                                                            positions_to_exit.append({
                                                                'symbol': symbol,
                                                                'quantity': quantity,
                                                                'reason': f'Coinbase time lockdown (held {position_age_minutes:.1f}min at {pnl_percent*100:+.2f}%)',
                                                                'broker': position_broker,
                                                                'broker_label': broker_label
                                                            })
                                                            continue

                                                    # EMERGENCY TIME-BASED EXIT: Force exit ALL positions after 12 hours (FAILSAFE)
                                                    # This is a last-resort failsafe for profitable positions that aren't hitting targets
                                                    if position_age_hours >= MAX_POSITION_HOLD_EMERGENCY:
                                                        logger.error(f"   🚨 EMERGENCY TIME EXIT: {symbol} held for {position_age_hours:.1f} hours (emergency max: {MAX_POSITION_HOLD_EMERGENCY})")
                                                        logger.error(f"   💥 FORCE SELLING to prevent indefinite holding!")
                                                        positions_to_exit.append({
                                                            'symbol': symbol,
                                                            'quantity': quantity,
                                                            'reason': f'EMERGENCY time exit (held {position_age_hours:.1f}h, max {MAX_POSITION_HOLD_EMERGENCY}h)',
                                                            'broker': position_broker,
                                                            'broker_label': broker_label
                                                        })
                                                    # TIME-BASED EXIT: Auto-exit stale positions
                                                    elif position_age_hours >= MAX_POSITION_HOLD_HOURS:
                                                        logger.warning(f"   ⏰ STALE POSITION EXIT: {symbol} held for {position_age_hours:.1f} hours (max: {MAX_POSITION_HOLD_HOURS})")
                                                        positions_to_exit.append({
                                                            'symbol': symbol,
                                                            'quantity': quantity,
                                                            'reason': f'Time-based exit (held {position_age_hours:.1f}h, max {MAX_POSITION_HOLD_HOURS}h)',
                                                            'broker': position_broker,
                                                            'broker_label': broker_label
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
                                            # If position is immediately losing, queue it for exit NOW (not next cycle!)
                                            if immediate_pnl < 0:
                                                logger.warning(f"   🚨 AUTO-IMPORTED LOSER: {symbol} at {immediate_pnl:.2f}%")
                                                logger.warning(f"   💥 Queuing for IMMEDIATE EXIT THIS CYCLE")
                                                positions_to_exit.append({
                                                    'symbol': symbol,
                                                    'quantity': quantity,
                                                    'reason': f'Auto-imported losing position ({immediate_pnl:+.2f}%)',
                                                    'broker': position_broker,
                                                    'broker_label': broker_label
                                                })
                                                # Skip all remaining logic for this position since it's queued for exit
                                                continue

                                            logger.info(f"      Position now tracked - will use profit targets in next cycle")
                                            logger.info(f"   ✅ AUTO-IMPORTED: {symbol} @ ${current_price:.2f} (P&L will start from $0) | "
                                                      f"⚠️  WARNING: This position may have been losing before auto-import! | "
                                                      f"Position now tracked - will evaluate exit in next cycle")

                                            # CRITICAL FIX: Don't mark as just_auto_imported to allow stop-loss to execute
                                            # Auto-imported positions should NOT skip stop-loss checks!
                                            # Only skip profit-taking logic to avoid premature exits
                                            just_auto_imported = False  # Changed from True - stop-loss must execute!

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
                                                'reason': f'Time-based exit without entry price (held {position_age_hours:.1f}h)',
                                                'broker': position_broker,
                                                'broker_label': broker_label
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
                                    'reason': 'Insufficient market data for analysis',
                                    'broker': position_broker,
                                    'broker_label': broker_label
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
                                    'reason': 'No indicators available',
                                    'broker': position_broker,
                                    'broker_label': broker_label
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
                                        'reason': f'Orphaned position with weak RSI ({rsi:.1f}) - preventing loss',
                                        'broker': position_broker,
                                        'broker_label': broker_label
                                    })
                                    continue

                                # Exit if price is below EMA9 (short-term weakness)
                                if current_price < ema9:
                                    logger.warning(f"   🚨 ORPHANED POSITION EXIT: {symbol} (price ${current_price:.2f} < EMA9 ${ema9:.2f})")
                                    logger.warning(f"      Exiting aggressively to prevent holding potential loser")
                                    positions_to_exit.append({
                                        'symbol': symbol,
                                        'quantity': quantity,
                                        'reason': f'Orphaned position below EMA9 - preventing loss',
                                        'broker': position_broker,
                                        'broker_label': broker_label
                                    })
                                    continue

                                # If orphaned position made it here, it's showing strength - still monitor closely
                                logger.info(f"   ✅ ORPHANED POSITION SHOWING STRENGTH: {symbol} (RSI={rsi:.1f}, price above EMA9)")
                                logger.info(f"      Will monitor with lenient criteria to allow P&L development (exit only on extreme RSI with confirmation)")

                            # PROFITABILITY FIX (Jan 28, 2026): REMOVE UNPROFITABLE RSI-ONLY EXITS
                            # Previous logic was exiting on RSI signals without verifying profitability
                            # This caused "buying low, selling low" and "buying high, selling high" scenarios
                            #
                            # KEY INSIGHT: RSI overbought/oversold indicates MOMENTUM, not profitability
                            # - Position can be overbought (RSI > 55) but still losing money
                            # - Position can be oversold (RSI < 45) but still making money
                            #
                            # NEW STRATEGY: For orphaned positions that passed aggressive checks (RSI >= 52, price >= EMA9)
                            # use EXTREME signals only to allow positions to develop proper P&L:
                            # - Only exit on VERY overbought (RSI > 70) with confirmed weakness (price < EMA9)
                            # - Only exit on VERY oversold (RSI < 30) with confirmed downtrend (price < EMA21)
                            # - Always verify price action confirms the RSI signal before exit
                            #
                            # This prevents premature exits and lets positions develop proper P&L

                            # EXTREME overbought (RSI > 70) with momentum weakening - likely reversal
                            # Only exit if price is also below EMA9 (confirming momentum loss)
                            if rsi > 70:
                                ema9 = indicators.get('ema_9', pd.Series()).iloc[-1] if 'ema_9' in indicators else current_price
                                if current_price < ema9:
                                    logger.info(f"   📈 EXTREME OVERBOUGHT + REVERSAL: {symbol} (RSI={rsi:.1f}, price<EMA9)")
                                    logger.info(f"      Exiting to protect against sharp reversal from overbought")
                                    positions_to_exit.append({
                                        'symbol': symbol,
                                        'quantity': quantity,
                                        'reason': f'Extreme overbought reversal (RSI={rsi:.1f}, price<EMA9)',
                                        'broker': position_broker,
                                        'broker_label': broker_label
                                    })
                                    continue
                                else:
                                    logger.info(f"   📊 {symbol} very overbought (RSI={rsi:.1f}) but still strong (price>EMA9) - HOLDING")
                                    continue

                            # REMOVED (Jan 28, 2026): Moderate RSI exits (RSI 45-55, RSI 50+) were too aggressive
                            # These exits were triggering without profit verification, causing:
                            # - Selling winners too early (RSI 50-55 exits at small gains)
                            # - Selling losers too late (RSI 45-50 exits after significant losses)
                            # Result: "Buying low, selling low" and minimal profits
                            #
                            # Now only extreme RSI levels (>70, <30) with confirming signals trigger exits
                            # This allows positions to develop proper P&L before exiting

                            # EXTREME oversold (RSI < 30) with continued weakness - likely further decline
                            # Only exit if price is also below EMA21 (confirming downtrend)
                            if rsi < 30:
                                ema21 = indicators.get('ema_21', pd.Series()).iloc[-1] if 'ema_21' in indicators else current_price
                                if current_price < ema21:
                                    logger.info(f"   📉 EXTREME OVERSOLD + DOWNTREND: {symbol} (RSI={rsi:.1f}, price<EMA21)")
                                    logger.info(f"      Exiting to prevent further losses in confirmed downtrend")
                                    positions_to_exit.append({
                                        'symbol': symbol,
                                        'quantity': quantity,
                                        'reason': f'Extreme oversold downtrend (RSI={rsi:.1f}, price<EMA21)',
                                        'broker': position_broker,
                                        'broker_label': broker_label
                                    })
                                    continue
                                else:
                                    logger.info(f"   📊 {symbol} very oversold (RSI={rsi:.1f}) but bouncing (price>EMA21) - HOLDING for recovery")
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
                                    'reason': market_reason,
                                    'broker': position_broker,
                                    'broker_label': broker_label
                                })
                                continue

                            # If we get here, position passes all checks - keep it
                            logger.info(f"   ✅ {symbol} passing all checks (RSI={rsi:.1f}, trend={trend})")

                        except Exception as e:
                            logger.error(f"   Error analyzing position {symbol}: {e}", exc_info=True)

                        # Rate limiting: Add delay after each position check to prevent 429 errors
                        # Skip delay after the last position
                        if idx < len(current_positions) - 1:
                            jitter = random.uniform(0, 0.05)  # 0-50ms jitter
                            time.sleep(POSITION_CHECK_DELAY + jitter)
                
                # NORMAL MODE: Under position cap, managing positions normally
                else:  # new_state == PositionManagementState.NORMAL
                    logger.info("=" * 70)
                    logger.info("✅ NORMAL MODE - Position Management")
                    logger.info("=" * 70)
                    logger.info(f"   📊 Positions: {len(current_positions)}/{MAX_POSITIONS_ALLOWED}")
                    logger.info(f"   ✅ Under cap - entries allowed")
                    logger.info(f"   🎯 Managing positions for optimal exits")
                    logger.info("=" * 70)
                    # In NORMAL mode, we still analyze all positions for potential exits
                    # but we're not in drain mode, so we don't need to force exits
                    # The existing position analysis code will handle this

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
                                    'reason': 'Over position cap (price fetch failed - symbol mismatch)',
                                    'broker': position_broker,
                                    'broker_label': broker_label
                                })
                                continue

                            value = quantity * price
                            logger.warning(f"   🔴 FORCE-EXIT to meet cap: {symbol} (${value:.2f})")
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': f'Over position cap (${value:.2f})',
                                'broker': position_broker,
                                'broker_label': broker_label
                            })
                        except Exception as price_err:
                            # Still add even if price fetch fails
                            logger.warning(f"   ⚠️ Could not get price for {symbol}: {price_err}")
                            positions_to_exit.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'reason': 'Over position cap',
                                'broker': position_broker,
                                'broker_label': broker_label
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

                    # Track sell results to provide accurate summary
                    successful_sells = []
                    failed_sells = []

                    for i, pos_data in enumerate(positions_to_exit, 1):
                        symbol = pos_data['symbol']
                        quantity = pos_data['quantity']
                        reason = pos_data['reason']
                        # CRITICAL FIX (Jan 24, 2026): Use the correct broker for each position
                        exit_broker = pos_data.get('broker', active_broker)
                        exit_broker_label = pos_data.get('broker_label', 'UNKNOWN')

                        logger.info(f"[{i}/{len(positions_to_exit)}] Selling {symbol} on {exit_broker_label} ({reason})")

                        # CRITICAL FIX (Jan 10, 2026): Validate symbol before placing order
                        # Prevents "ProductID is invalid" errors
                        if not symbol or not isinstance(symbol, str):
                            logger.error(f"  ❌ SKIPPING: Invalid symbol (value: {symbol}, type: {type(symbol)})")
                            # Store descriptive string for logging - will be displayed in summary
                            failed_sells.append(f"INVALID_SYMBOL({symbol})")
                            continue

                        try:
                            # 🚨 COINBASE LOCKDOWN (Jan 2026) - FORCE LIQUIDATE MODE
                            # Use force_liquidate for Coinbase sells to bypass ALL validation
                            # This ensures stop-losses and profit-taking ALWAYS execute
                            is_coinbase = 'coinbase' in exit_broker_label.lower()
                            use_force_liquidate = is_coinbase and ('lockdown' in reason.lower() or 'loss' in reason.lower() or 'stop' in reason.lower())

                            if use_force_liquidate:
                                logger.info(f"  🛡️ PROTECTIVE MODE: Using force_liquidate for Coinbase exit")

                            result = exit_broker.place_market_order(
                                symbol=symbol,
                                side='sell',
                                quantity=quantity,
                                size_type='base',
                                force_liquidate=use_force_liquidate,  # Bypass ALL validation for Coinbase protective exits
                                ignore_balance=use_force_liquidate,   # Skip balance checks
                                ignore_min_trade=use_force_liquidate  # Skip minimum trade size checks
                            )

                            # Handle dust positions separately from actual failures
                            if result and result.get('status') == 'skipped_dust':
                                logger.info(f"  💨 {symbol} SKIPPED (dust position - too small to sell)")
                                logger.info(f"     Will automatically retry in 24h if position grows")
                                # Mark as unsellable for 24h retry window
                                self.unsellable_positions[symbol] = time.time()
                                # Don't add to failed_sells - this is expected behavior for dust
                                continue

                            if result and result.get('status') not in ['error', 'unfilled']:
                                logger.info(f"  ✅ {symbol} SOLD successfully on {exit_broker_label}!")
                                # ✅ FIX #3: EXPLICIT SELL CONFIRMATION LOG
                                # If this was a stop-loss exit, log it clearly
                                if 'stop loss' in reason.lower():
                                    logger.info(f"  ✅ SOLD {symbol} @ market due to stop loss")
                                # Track the exit in position tracker (use the correct broker)
                                if hasattr(exit_broker, 'position_tracker') and exit_broker.position_tracker:
                                    exit_broker.position_tracker.track_exit(symbol, quantity)
                                # Remove from unsellable dict if it was there (position grew and became sellable)
                                if symbol in self.unsellable_positions:
                                    del self.unsellable_positions[symbol]
                                successful_sells.append(symbol)
                            else:
                                error_msg = result.get('error', result.get('message', 'Unknown')) if result else 'No response'
                                error_code = result.get('error') if result else None
                                logger.error(f"  ❌ {symbol} sell failed: {error_msg}")
                                logger.error(f"     Full result: {result}")
                                failed_sells.append(symbol)

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
                            # Convert symbol to string for consistent logging - prevents join() errors
                            failed_sells.append(str(symbol) if symbol else "UNKNOWN_SYMBOL")

                        # Rate limiting: Add delay after each sell order (except the last one)
                        if i < len(positions_to_exit):
                            jitter = random.uniform(0, 0.1)  # 0-100ms jitter
                            time.sleep(SELL_ORDER_DELAY + jitter)

                    logger.info(f"="*80)
                    # CRITICAL FIX (Jan 22, 2026): Provide accurate exit summary with success/failure counts
                    # Previous version logged "positions processed" which was misleading - users thought all sells succeeded
                    logger.info(f"🔴 CONCURRENT EXIT SUMMARY:")
                    logger.info(f"   ✅ Successfully sold: {len(successful_sells)} positions")
                    if successful_sells:
                        logger.info(f"      {', '.join(successful_sells)}")
                    logger.info(f"   ❌ Failed to sell: {len(failed_sells)} positions")
                    if failed_sells:
                        logger.error(f"      {', '.join(failed_sells)}")
                        logger.error(f"   🚨 WARNING: {len(failed_sells)} position(s) still open on exchange!")
                        logger.error(f"   💡 Check Coinbase manually and retry or sell manually if needed")
                    logger.info(f"="*80)
                    logger.info(f"")

                # CRITICAL FIX: Ensure position management errors don't crash the entire cycle
                # If exit logic fails, log the error but continue to allow next cycle to retry
            except Exception as exit_err:
                logger.error("=" * 80)
                logger.error("🚨 POSITION MANAGEMENT ERROR")
                logger.error("=" * 80)
                logger.error(f"   Error during position management: {exit_err}")
                logger.error(f"   Type: {type(exit_err).__name__}")
                logger.error("   Exit logic will retry next cycle (2.5 min)")
                logger.error("=" * 80)
                import traceback
                logger.error(traceback.format_exc())
                # Don't return - allow cycle to continue and try new entries
                # This ensures the bot keeps running even if exit logic fails

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
                logger.info("   ℹ️  USER accounts execute copied trades only")
                logger.info("   ℹ️  USER accounts do not scan markets independently")
                logger.info("═" * 80)
                logger.info("")
            else:
                logger.info("   ✅ Mode: PLATFORM (full strategy execution)")
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

                # CRITICAL FIX (Jan 24, 2026): Wrap entire broker selection in try-catch
                # to prevent silent failures that cause market scanning to never execute
                try:
                    # Get all available brokers for selection
                    all_brokers = {}
                    if hasattr(self, 'multi_account_manager') and self.multi_account_manager:
                        # ensure mutable broker registry
                        all_brokers = dict(getattr(self.multi_account_manager, 'platform_brokers', {}))

                    # Add current active broker if not in multi_account_manager
                    if active_broker and hasattr(active_broker, 'broker_type'):
                        all_brokers[active_broker.broker_type] = active_broker

                    # CRITICAL FIX (Jan 24, 2026): Log if no brokers are available for selection
                    # This helps diagnose why no trades are executing
                    if not all_brokers:
                        logger.warning(f"      ⚠️  No brokers available for selection!")
                        logger.warning(f"      Multi-account manager: {'Yes' if self.multi_account_manager else 'No'}")
                        logger.warning(f"      Active broker: {'Yes' if active_broker else 'No'}")
                    else:
                        logger.info(f"      Available brokers for selection: {', '.join([bt.value.upper() for bt in all_brokers.keys()])}")

                    # Select best broker for entry based on priority
                    entry_broker, entry_broker_name, broker_eligibility = self._select_entry_broker(all_brokers)

                    # Note: Broker eligibility logging moved to after exception handler (line ~3420)
                    # to ensure it happens even if an exception occurs

                    if not entry_broker:
                        can_enter = False
                        skip_reasons.append("No eligible broker for entry (all in EXIT_ONLY or below minimum balance)")
                        logger.warning(f"   ❌ CONDITION FAILED: No eligible broker for entry")
                        logger.warning(f"      💡 All brokers are either in EXIT-ONLY mode or below minimum balance")
                    else:
                        logger.info(f"   ✅ CONDITION PASSED: {entry_broker_name.upper()} available for entry")
                        # Update active_broker to use the selected entry broker
                        active_broker = entry_broker

                        # CRITICAL FIX (Jan 26, 2026): Update apex strategy's broker reference
                        # When switching brokers, we must update the execution engine's broker
                        # Otherwise position sizing is calculated correctly but execution uses wrong broker
                        # This was causing KRAKEN trades ($57.31) to be executed with COINBASE balance ($24.16)
                        if self.apex and hasattr(self.apex, 'update_broker_client'):
                            logger.info(f"   🔄 Updating apex strategy broker to {entry_broker_name.upper()}")
                            self.apex.update_broker_client(active_broker)

                        # CRITICAL FIX (Jan 22, 2026): Update account_balance from selected entry broker
                        # When switching brokers, we must re-fetch the balance from the NEW broker
                        # Otherwise position sizing uses the wrong broker's balance (e.g., Coinbase $20 instead of Kraken $28)
                        # CRITICAL FIX (Jan 26, 2026): Wrap balance fetch in timeout to prevent hanging
                        # Without timeout, slow Kraken API calls can block indefinitely, preventing market scanning
                        balance_data = None
                        balance_fetch_failed = False

                        try:
                            if hasattr(active_broker, 'get_account_balance_detailed'):
                                # Use timeout to prevent hanging on slow balance fetches
                                balance_result = call_with_timeout(
                                    active_broker.get_account_balance_detailed,
                                    timeout_seconds=BALANCE_FETCH_TIMEOUT
                                )

                                if balance_result[1] is not None:  # Timeout or error
                                    logger.warning(f"   ⚠️  {entry_broker_name.upper()} detailed balance fetch timed out: {balance_result[1]}")
                                    balance_fetch_failed = True
                                else:
                                    balance_data = balance_result[0]
                            else:
                                # Fallback to simple balance fetch with timeout
                                balance_result = call_with_timeout(
                                    active_broker.get_account_balance,
                                    timeout_seconds=BALANCE_FETCH_TIMEOUT
                                )

                                if balance_result[1] is not None:  # Timeout or error
                                    logger.warning(f"   ⚠️  {entry_broker_name.upper()} balance fetch timed out: {balance_result[1]}")
                                    balance_fetch_failed = True
                                else:
                                    balance_data = {'trading_balance': balance_result[0]}
                        except Exception as e:
                            logger.warning(f"   ⚠️  {entry_broker_name.upper()} balance fetch exception: {e}")
                            balance_fetch_failed = True

                        # Use cached balance if fresh fetch failed
                        if balance_fetch_failed or balance_data is None:
                            if hasattr(active_broker, '_last_known_balance') and active_broker._last_known_balance is not None:
                                cached_balance = active_broker._last_known_balance

                                # Check if cached balance has a timestamp and is fresh
                                cache_is_fresh = False
                                if hasattr(active_broker, '_balance_last_updated') and active_broker._balance_last_updated is not None:
                                    balance_age_seconds = time.time() - active_broker._balance_last_updated
                                    cache_is_fresh = balance_age_seconds <= CACHED_BALANCE_MAX_AGE_SECONDS
                                    if not cache_is_fresh:
                                        logger.warning(f"   ⚠️  Cached balance for {entry_broker_name.upper()} is stale ({balance_age_seconds:.0f}s old > {CACHED_BALANCE_MAX_AGE_SECONDS}s max)")
                                else:
                                    # No timestamp - use cache anyway since fetch failed (better than nothing)
                                    cache_is_fresh = True
                                    logger.warning(f"   ⚠️  Cached balance for {entry_broker_name.upper()} has no timestamp, using anyway due to fetch failure")

                                if cache_is_fresh:
                                    logger.warning(f"   ⚠️  Using cached balance for {entry_broker_name.upper()}: ${cached_balance:.2f}")
                                    balance_data = {'trading_balance': cached_balance, 'total_held': 0.0, 'total_funds': cached_balance}
                                else:
                                    # Stale cache and fresh fetch failed - use eligibility check balance
                                    logger.error(f"   ❌ Cached balance too stale for {entry_broker_name.upper()}")
                                    logger.warning(f"   ⚠️  Using balance from eligibility check as fallback: ${account_balance:.2f}")
                                    balance_data = {'trading_balance': account_balance, 'total_held': 0.0, 'total_funds': account_balance}
                            else:
                                logger.error(f"   ❌ No cached balance available for {entry_broker_name.upper()}")
                                # Use the balance from eligibility check as last resort
                                logger.warning(f"   ⚠️  Using balance from eligibility check as fallback: ${account_balance:.2f}")
                                balance_data = {'trading_balance': account_balance, 'total_held': 0.0, 'total_funds': account_balance}

                        account_balance = balance_data.get('trading_balance', 0.0)

                        # Also update position values and total capital from the new broker
                        held_funds = balance_data.get('total_held', 0.0)
                        total_funds = balance_data.get('total_funds', account_balance)

                        # Fetch total capital with timeout protection
                        if hasattr(active_broker, 'get_total_capital'):
                            try:
                                capital_result = call_with_timeout(
                                    active_broker.get_total_capital,
                                    kwargs={'include_positions': True},
                                    timeout_seconds=BALANCE_FETCH_TIMEOUT
                                )

                                if capital_result[1] is not None:  # Timeout or error
                                    logger.warning(f"   ⚠️  {entry_broker_name.upper()} capital fetch timed out: {capital_result[1]}")
                                    total_capital = account_balance
                                else:
                                    capital_data = capital_result[0]
                                    position_value = capital_data.get('position_value', 0.0)
                                    position_count = capital_data.get('position_count', 0)
                                    total_capital = capital_data.get('total_capital', account_balance)
                            except Exception as e:
                                logger.debug(f"⚠️ Could not calculate position values from entry broker: {e}")
                                total_capital = account_balance
                        else:
                            total_capital = account_balance

                        logger.info(f"   💰 {entry_broker_name.upper()} balance updated: ${account_balance:.2f} (total capital: ${total_capital:.2f})")

                except Exception as broker_check_error:
                    # CRITICAL FIX (Jan 27, 2026): Enhanced exception logging with line number
                    # This helps diagnose exactly where broker selection is failing
                    logger.error(f"   ❌ ERROR during broker eligibility check: {broker_check_error}")
                    logger.error(f"   Exception type: {type(broker_check_error).__name__}")
                    import traceback
                    logger.error(f"   Traceback: {traceback.format_exc()}")
                    logger.error(f"   ⚠️  This error prevented broker selection - bot will skip market scanning")
                    can_enter = False
                    skip_reasons.append(f"Broker eligibility check failed: {broker_check_error}")
                    # Set entry_broker to None to ensure it's defined for later code
                    entry_broker = None
                    entry_broker_name = "UNKNOWN"
                    # Initialize empty broker_eligibility dict if it wasn't created
                    if 'broker_eligibility' not in locals():
                        broker_eligibility = {}

                # CRITICAL FIX (Jan 27, 2026): Always log broker eligibility status
                # Even if exception occurred, we want to see which brokers were checked
                if 'broker_eligibility' in locals() and broker_eligibility:
                    logger.info("")
                    logger.info("   📊 Broker Eligibility Results:")
                    for broker_name, status in broker_eligibility.items():
                        if "Eligible" in status:
                            logger.info(f"      ✅ {broker_name.upper()}: {status}")
                        elif "Not configured" in status:
                            logger.info(f"      ⚪ {broker_name.upper()}: {status}")
                        else:
                            logger.warning(f"      ❌ {broker_name.upper()}: {status}")

                logger.info("")
                logger.info("═" * 80)

                if can_enter:
                    logger.info(f"🟢 RESULT: CONDITIONS PASSED FOR {entry_broker_name.upper()}")
                    logger.info("═" * 80)
                    logger.info("")
                else:
                    logger.warning("🔴 RESULT: CONDITIONS FAILED - SKIPPING MARKET SCAN")
                    # 🧠 TRUST LAYER: Explicit trade veto reason logging
                    logger.warning("=" * 70)
                    logger.warning("🚫 TRADE VETO - Signal Blocked from Execution")
                    logger.warning("=" * 70)
                    for idx, reason in enumerate(skip_reasons, 1):
                        logger.warning(f"   Veto Reason {idx}: {reason}")
                    logger.warning("=" * 70)
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

                            # WHITELIST CHECK - Only trade whitelisted symbols if whitelist is enabled
                            if WHITELIST_ENABLED:
                                broker_name = self._get_broker_name(active_broker)
                                if not is_whitelisted_symbol(symbol, broker_name):
                                    logger.debug(f"   ⏭️  SKIPPING {symbol}: Not in whitelist (only trading {', '.join(WHITELISTED_ASSETS)})")
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

                            # ═══════════════════════════════════════════════════════
                            # MARKET READINESS GATE - Check market conditions
                            # ═══════════════════════════════════════════════════════
                            # Calculate required indicators for market readiness check
                            if self.market_readiness_gate is not None:
                                try:
                                    # Calculate indicators needed for readiness check
                                    current_price = df['close'].iloc[-1]
                                    
                                    # Calculate ATR if not already in df
                                    if 'atr' not in df.columns:
                                        from indicators import calculate_atr
                                        df['atr'] = calculate_atr(df, period=14)
                                    atr = scalar(df['atr'].iloc[-1])
                                    
                                    # Calculate ADX if not already in df
                                    if 'adx' not in df.columns:
                                        from indicators import calculate_adx
                                        df['adx'] = calculate_adx(df, period=14)
                                    adx = scalar(df['adx'].iloc[-1])
                                    
                                    # Calculate volume percentile (current volume vs 24h average)
                                    volume_percentile = 50.0  # Default to neutral
                                    if 'volume' in df.columns and len(df) >= 20:
                                        current_volume = df['volume'].iloc[-1]
                                        avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]
                                        if avg_volume > 0:
                                            volume_ratio = current_volume / avg_volume
                                            # Convert ratio to percentile (0.5 = 50%, 1.0 = 100%, 2.0 = 200%)
                                            volume_percentile = min(100, volume_ratio * 50)
                                    
                                    # Estimate spread (TODO: get real bid/ask from broker)
                                    spread_pct = 0.001  # Conservative 0.1% estimate
                                    
                                    # Check market readiness (pass None for entry_score initially)
                                    mode, conditions, details = self.market_readiness_gate.check_market_readiness(
                                        atr=atr,
                                        current_price=current_price,
                                        adx=adx,
                                        volume_percentile=volume_percentile,
                                        spread_pct=spread_pct,
                                        entry_score=None  # Will check again after scoring
                                    )
                                    
                                    # Block entries in IDLE mode
                                    if mode == MarketMode.IDLE:
                                        logger.debug(f"   ⏸️  {symbol}: IDLE MODE - {details['message']}")
                                        filter_stats['market_filter'] += 1
                                        continue
                                    
                                except Exception as readiness_err:
                                    logger.debug(f"   ⚠️ Market readiness check error for {symbol}: {readiness_err}")
                                    # Continue with analysis if readiness check fails

                            # Analyze for entry
                            # CRITICAL: Use broker-specific balance for position sizing
                            # PRO MODE: Include broker's position values (total capital)
                            # STANDARD MODE: Use only broker's free balance
                            # NOTE: Both account_balance and total_capital are broker-specific at this point
                            # (updated at lines 3418 and 3440 from selected entry broker)
                            broker_balance = total_capital if self.pro_mode_enabled else account_balance
                            analysis = self.apex.analyze_market(df, symbol, broker_balance)
                            
                            # ═══════════════════════════════════════════════════════
                            # LAYER 2: TRADE QUALITY GATE
                            # ═══════════════════════════════════════════════════════
                            # Filter trades through quality gate (R:R, momentum, stop quality)
                            if hasattr(self, 'quality_gate') and self.quality_gate:
                                analysis = self.quality_gate.filter_strategy_signal(analysis, df)
                            
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
                                entry_score = analysis.get('score', 0)  # Get entry score from analysis

                                # ═══════════════════════════════════════════════════════
                                # MARKET READINESS GATE - Re-check with entry score for CAUTIOUS mode
                                # ═══════════════════════════════════════════════════════
                                if self.market_readiness_gate is not None:
                                    try:
                                        # Re-check market readiness with actual entry score
                                        # This enables CAUTIOUS mode filtering (requires score ≥85)
                                        mode, conditions, details = self.market_readiness_gate.check_market_readiness(
                                            atr=atr,
                                            current_price=current_price,
                                            adx=adx,
                                            volume_percentile=volume_percentile,
                                            spread_pct=spread_pct,
                                            entry_score=entry_score
                                        )
                                        
                                        # Apply mode-specific position size adjustments
                                        if mode == MarketMode.IDLE:
                                            logger.info(f"   ⏸️  {symbol}: IDLE MODE - No entries allowed")
                                            logger.info(f"      {details['message']}")
                                            filter_stats['market_filter'] += 1
                                            continue
                                        elif mode == MarketMode.CAUTIOUS:
                                            if not details['allow_entries']:
                                                logger.info(f"   ⚠️  {symbol}: CAUTIOUS MODE - Entry blocked (score {entry_score:.0f} < 85)")
                                                filter_stats['market_filter'] += 1
                                                continue
                                            else:
                                                # CAUTIOUS mode: Cap position size at 20% of normal
                                                cautious_multiplier = details.get('position_size_multiplier', 0.20)
                                                original_size = position_size
                                                position_size = position_size * cautious_multiplier
                                                logger.info(f"   ⚠️  {symbol}: CAUTIOUS MODE - Position size reduced to {cautious_multiplier*100:.0f}%")
                                                logger.info(f"      Original: ${original_size:.2f} → Cautious: ${position_size:.2f}")
                                                logger.info(f"      Entry score: {entry_score:.0f}/100 (A+ setup)")
                                        elif mode == MarketMode.AGGRESSIVE:
                                            logger.debug(f"   🚀 {symbol}: AGGRESSIVE MODE - Full position sizing")
                                        
                                    except Exception as readiness_err:
                                        logger.warning(f"   ⚠️ Market readiness re-check error for {symbol}: {readiness_err}")
                                        # Continue with trade if readiness check fails

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
                                    logger.info(f"      💡 Kraken requires ${MIN_POSITION_SIZE} minimum trade size per exchange rules")
                                    logger.info(f"      📊 Current balance: ${account_balance:.2f}")
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

                                # CRITICAL: Verify we're still under position cap before placing order
                                if len(current_positions) >= MAX_POSITIONS_ALLOWED:
                                    logger.error(f"   ❌ SAFETY VIOLATION: Position cap ({MAX_POSITIONS_ALLOWED}) reached - BLOCKING NEW ENTRY")
                                    logger.error(f"      Current positions: {len(current_positions)}")
                                    logger.error(f"      This should not happen - cap should have been checked earlier!")
                                    break
                                
                                logger.info(f"   ✅ Final position cap check: {len(current_positions)}/{MAX_POSITIONS_ALLOWED} - OK to enter")

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

                    # EXPLICIT: Log waiting status when no signals found
                    if filter_stats['signals_found'] == 0:
                        logger.info("")
                        logger.info("   ⏳ WAITING FOR PLATFORM ENTRY")
                        logger.info("   → No qualifying signals found in this cycle")
                        logger.info("   → Will continue monitoring markets...")

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
            
            # SAFETY VERIFICATION: Check position count at end of cycle
            try:
                if active_broker:
                    final_positions = active_broker.get_positions()
                    final_count = len(final_positions)
                    
                    if final_count > MAX_POSITIONS_ALLOWED:
                        logger.error(f"")
                        logger.error(f"❌ SAFETY VIOLATION DETECTED AT END OF CYCLE!")
                        logger.error(f"   Position count: {final_count}")
                        logger.error(f"   Maximum allowed: {MAX_POSITIONS_ALLOWED}")
                        logger.error(f"   Excess positions: {final_count - MAX_POSITIONS_ALLOWED}")
                        logger.error(f"   ⚠️ CRITICAL: Cap enforcement failed - this should never happen!")
                        logger.error(f"")
                    elif final_count == MAX_POSITIONS_ALLOWED:
                        logger.info(f"✅ Position cap verification: At cap ({final_count}/{MAX_POSITIONS_ALLOWED})")
                    else:
                        logger.info(f"✅ Position cap verification: Under cap ({final_count}/{MAX_POSITIONS_ALLOWED})")
            except Exception as verify_err:
                logger.debug(f"Position count verification skipped: {verify_err}")

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
        
        # Record with Market Readiness Gate for win rate tracking
        if hasattr(self, 'market_readiness_gate') and self.market_readiness_gate:
            try:
                # Calculate profit as percentage (assumes $100 position size for approximation)
                # TODO: Track actual position size for accurate percentage calculation
                pnl_pct = (profit_usd / 100.0) if profit_usd != 0 else 0.0
                self.market_readiness_gate.record_trade_result(pnl_pct)
            except Exception as e:
                logger.warning(f"Failed to record trade in market readiness gate: {e}")

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
