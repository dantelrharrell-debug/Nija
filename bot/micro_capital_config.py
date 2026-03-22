"""
NIJA Micro Capital Mode Configuration
======================================

Configuration for micro capital accounts ($15-$500) with:
- Optimized for small capital fast-frequency trading (Pro-Level)
- Dynamic position scaling based on equity
- Kraken as PRIMARY broker (Coinbase disabled Jan 30, 2026)
- Advanced signal filtering and AI trade validation
- Automatic feature enablement as capital grows

Optimized for:
- Small capital fast-frequency trading
- Pro-Level position sizing (25% max per position for micro capital)
- Higher position count (5 concurrent positions)
- Tight risk management (0.7% risk per trade)
- Gradual scaling with account growth

Author: NIJA Trading Systems
Version: 2.1
Date: January 30, 2026
Updated: Kraken as exclusive primary broker (Coinbase disabled)
"""

import os
import logging
from typing import Dict, Optional, Union

logger = logging.getLogger("nija.micro_capital_config")

# ============================================================================
# OPERATIONAL MODE
# ============================================================================

MICRO_CAPITAL_MODE = True

# Trading mode configuration
MODE = "PLATFORM_ONLY"  # Only platform account trades (no copy trading initially)

# Broker configuration (UPDATED Jan 30, 2026: Coinbase disabled)
PRIMARY_BROKER = "KRAKEN"  # Changed from COINBASE to KRAKEN
SECONDARY_BROKER = None    # No secondary broker (Coinbase disabled)

# Live trading settings
LIVE_TRADING = True
PRO_MODE = True
TRADING_MODE = "independent"  # Independent trading mode (no copy trading)

# ============================================================================
# BALANCE AND TRADE SIZE REQUIREMENTS
# ============================================================================

MIN_BALANCE_TO_TRADE = 15.00  # Minimum account balance to start trading
MIN_TRADE_SIZE = 5.00  # Minimum trade size in USD

# ============================================================================
# POSITION MANAGEMENT
# ============================================================================

# Pro-Level Optimization (Jan 30, 2026):
# - MAX_POSITIONS = 8: Upper bound of the 3–8 position range for micro accounts
# - MIN_POSITIONS = 3: Lower bound — applied at the base of the micro account range ($100)
# - MAX_POSITION_PCT = 25%: Larger individual positions for small capital efficiency
# - RISK_PER_TRADE = 0.9%: Balanced risk control per trade
#
# Micro account position scaling (Mar 2026):
#   Balance $100–$500 → max_positions scales linearly from MIN_POSITIONS (3) to MAX_POSITIONS (8)
#   This replaces the old fixed value of 4 with a dynamic 3–8 range so that accounts
#   approaching $500 can diversify further while very small accounts stay concentrated.
#
# NOTE: While MAX_POSITIONS × MAX_POSITION_PCT = 100% theoretical maximum,
# the risk_manager.py enforces max_total_exposure = 60% as a safeguard.
# This configuration is optimized for fast-frequency trading where not all
# positions will be at maximum size simultaneously.

MIN_POSITIONS = 3  # Minimum concurrent positions for micro accounts (lower bound of 3–8 range)
MAX_POSITIONS = 8  # Maximum concurrent positions for micro accounts (upper bound of 3–8 range)

# Position sizing as percentage of capital
MAX_POSITION_PCT = 25.0  # Maximum 25% of capital per position (OPTIMIZED for small capital fast-frequency)
RISK_PER_TRADE = 0.9  # Risk 0.9% per trade (OPTIMIZED for Pro-Level performance)

# CRITICAL: DCA and Multiple Entries (Feb 17, 2026 - ORDER MANAGEMENT FIX)
# For MICRO_CAP accounts, we DISABLE:
# - DCA (Dollar Cost Averaging)
# - Multiple concurrent entries on same symbol
# Reason: Order fragmentation kills performance in micro accounts
ENABLE_DCA = False  # DISABLED for micro capital (prevents averaging down)
ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL = False  # DISABLED - one position per symbol max

# ============================================================================
# IDEAL MICRO CONFIGURATION (Mar 2026)
# Optimised settings that dramatically improve growth without increasing risk.
# Professional systems use score weighting instead of hard filters (see
# market_structure_filter.py for the scoring logic).
# ============================================================================

MAX_CONCURRENT_TRADES = 4   # Maximum simultaneous open trades
CAPITAL_PER_TRADE = 20.0    # Percentage of total capital allocated per trade (%)
ENTRY_SCAN_INTERVAL = 15    # Seconds between entry-opportunity scans (was 20 – faster for micro growth)
MONITOR_INTERVAL = 45       # Seconds between open-position monitoring cycles

# ============================================================================
# RISK MANAGEMENT
# ============================================================================

DAILY_MAX_LOSS = 6.0  # Maximum 6% daily loss
MAX_DRAWDOWN = 12.0  # Maximum 12% drawdown before stopping

# Position sizer configuration
POSITION_SIZER = "HYBRID"

# Hybrid position sizing weights
KELLY_WEIGHT = 0.30
VOLATILITY_WEIGHT = 0.40
EQUITY_WEIGHT = 0.30

# ============================================================================
# SIGNAL FILTERING
# ============================================================================

MIN_SIGNAL_SCORE = 0.68  # Minimum signal quality score on 0-1 scale (was 0.75). NOTE: this is overridden
                         # by the 0-100 scale MIN_SIGNAL_SCORE in the ADVANCED OPTIMIZATION block below.
MIN_AI_CONFIDENCE = 0.65  # Minimum AI confidence level (65% — was 70%, more signals while maintaining quality gate)
MIN_RISK_REWARD = 1.8  # Minimum risk/reward ratio

# ============================================================================
# TRADING PAIRS
# ============================================================================

TRADE_ONLY = ["BTC", "ETH", "SOL", "XRP", "ADA"]  # Major liquid cryptocurrencies (expanded for more opportunities)

# ============================================================================
# ADVANCED FEATURES
# ============================================================================

MARKET_REGIME_ENGINE = True  # Enable market regime detection
SIGNAL_ENSEMBLE = True  # Use ensemble of signals
AI_TRADE_FILTER = True  # Enable AI-based trade filtering

# ============================================================================
# LEVERAGE AND ARBITRAGE
# ============================================================================

LEVERAGE_ENABLED = False  # No leverage initially (enabled at $1000+)
ARBITRAGE = False  # Arbitrage disabled

# ============================================================================
# SAFETY AND ERROR HANDLING
# ============================================================================

AUTO_SHUTOFF_ON_ERRORS = True  # Auto-shutoff on consecutive errors
MAX_CONSECUTIVE_LOSSES = 3  # Maximum consecutive losses before pause

# ============================================================================
# CAPITAL ALLOCATION
# ============================================================================

FORCE_CASH_BUFFER = 10.0  # Keep 10% of capital unallocated (was 15% — deploy more capital for faster growth)

# ============================================================================
# EXCHANGE PRIORITY
# ============================================================================

EXCHANGE_PRIORITY = ["KRAKEN"]  # Only Kraken (Coinbase disabled Jan 30, 2026)

# Minimum balances per exchange
MIN_BALANCE_KRAKEN = 10.0  # Lowered to match previous Coinbase minimum
# MIN_BALANCE_COINBASE = 10.0  # Coinbase disabled

# ============================================================================
# MICRO-CAP COMPOUNDING MODE (balance < $100)
# ============================================================================
# High-performing compounding bots concentrate capital: rather than spreading
# across dozens of small trades, this mode executes only high-conviction
# trades per session, each using a large fraction of available capital.
#
#   - max_positions    = 1      (one trade at a time — maximum concentration)
#   - position_size    = 90%    (maximise capital per trade; e.g. $39 of a $43 account)
#   - profit_target    = 2.5%   (realistic per-trade target to compound quickly)
#   - stop_loss        = 1.5%   (below profit target → ≥1.67:1 R:R ratio)
#   - trade_cooldown   = 600s   (10-min per-symbol re-entry gate — was 15 min)
#
# Adaptive Profit Scaling:
#   The profit target may scale UP above the 2.5% base during favourable
#   conditions (consecutive wins, elevated volatility). The base target is
#   always the floor — it never drops below 2.5%.
#   Scale caps at MICRO_CAP_ADAPTIVE_PROFIT_MAX_PCT (8.0%).
#   - profit_target    = base_target + spread + streak_bonus  (fully dynamic)
#                          base_target  = 2.5%
#                          spread       = current market spread
#                          streak_bonus = +0.2% per consecutive win (capped at +1.0%)
#                          After any loss: win_streak resets to 0 → no streak bonus
#   - stop_loss        = 1.5%   (below base profit target → ≥1.67:1 R:R ratio on base)
#   - trade_cooldown   = 600s   (10-min per-symbol cooldown between trades)

MICRO_CAP_COMPOUNDING_BALANCE_THRESHOLD = 100.0  # Activate below $100
MICRO_CAP_COMPOUNDING_MAX_POSITIONS = 1          # Single position — maximum capital concentration
MICRO_CAP_COMPOUNDING_POSITION_SIZE_PCT = 90.0   # 90% of capital per trade (maximise compounding speed)
MICRO_CAP_COMPOUNDING_PROFIT_TARGET_PCT = 2.5    # 2.5% profit target (was 3.0% — achievable faster)
MICRO_CAP_COMPOUNDING_STOP_LOSS_PCT = 1.5        # 1.5% stop loss (≥1.67:1 R:R)
MICRO_CAP_TRADE_COOLDOWN = 600                   # 10-min per-symbol re-entry gate (was 900 s / 15 min)

# Tiered profit targets for micro-cap compounding mode
MICRO_CAP_TP1_PCT = 2.5   # Target 1: 2.5% — partial exit + activate trailing stop (was 3.0%)
MICRO_CAP_TP2_PCT = 3.5   # Target 2: 3.5% — second partial exit (was 4.5%)
MICRO_CAP_TP3_PCT = 6.0   # Target 3: 6.0% — final exit / full runner target
MICRO_CAP_TRAILING_STOP_ACTIVATION_PCT = 2.5  # Trailing stop activates after 2.5% profit (was 3.0%)

# Adaptive Profit Scaling — scales target UP in favourable conditions only
MICRO_CAP_ADAPTIVE_PROFIT_SCALING = True         # Enable adaptive profit scaling
MICRO_CAP_ADAPTIVE_PROFIT_MIN_PCT = 2.5          # Minimum profit target (equals base — was 3.0%)
MICRO_CAP_ADAPTIVE_PROFIT_MAX_PCT = 8.0          # Maximum profit target under scaling (raised for fast scaling)
MICRO_CAP_ADAPTIVE_PROFIT_WIN_STREAK_SCALE = 0.2 # Extra % per consecutive winning trade (up from 0.1)
MICRO_CAP_ADAPTIVE_PROFIT_VOLATILITY_SCALE = True # Also scale with market volatility

# MICRO-CAP COMPOUNDING MODE HELPERS
MICRO_CAP_COMPOUNDING_PROFIT_TARGET_BASE_PCT = 2.5  # 2.5% base profit target (was 3.0% — spread + streak bonus added at runtime)
# Backward-compatible alias used as the static fallback when no spread data is available
MICRO_CAP_COMPOUNDING_PROFIT_TARGET_PCT = MICRO_CAP_COMPOUNDING_PROFIT_TARGET_BASE_PCT
MICRO_CAP_COMPOUNDING_STOP_LOSS_PCT = 1.5        # 1.5% stop loss (≥1.67:1 R:R vs base target)
MICRO_CAP_TRADE_COOLDOWN = 600                   # 10-min per-symbol re-entry cooldown (was 900 s)

# Win-streak bonus applied on top of (base + spread) while on a hot streak.
# The bonus is reset to 0 whenever a trade ends in a loss so the bot does not
# chase extended targets after momentum ends.
MICRO_CAP_WIN_STREAK_BONUS_PER_WIN = 0.2  # +0.2% per consecutive win (up from 0.1)
MICRO_CAP_WIN_STREAK_BONUS_MAX = 1.0      # cap at +1.0% (5 consecutive wins)


def get_spread_adjusted_profit_target(spread_pct: float, win_streak: int = 0) -> float:
    """
    Calculate the spread- and streak-adjusted profit target for micro-cap compounding mode.

    Formula:
        profit_target = base_target + spread + streak_bonus

    where:
        base_target  = MICRO_CAP_COMPOUNDING_PROFIT_TARGET_BASE_PCT (1.0%)
        spread       = current market spread expressed as a percentage
        streak_bonus = min(MICRO_CAP_WIN_STREAK_BONUS_MAX,
                          win_streak * MICRO_CAP_WIN_STREAK_BONUS_PER_WIN)

    The streak bonus rewards sustained momentum but is immediately reset to 0
    after any losing trade (win_streak = 0), preventing the bot from chasing
    extended targets when momentum has ended.

    Examples (assuming win_streak=0):
        spread 0.20%  →  profit target 1.20%
        spread 0.40%  →  profit target 1.40%
        spread 0.60%  →  profit target 1.60%

    Examples (assuming win_streak=3, bonus=0.3%):
        spread 0.20%  →  profit target 1.50%
        spread 0.40%  →  profit target 1.70%

    Args:
        spread_pct: Current bid-ask spread as a decimal fraction (e.g. 0.002 = 0.2%).
        win_streak:  Number of consecutive winning trades. Resets to 0 after any loss.

    Returns:
        Profit target as a percentage (e.g. 1.4 means 1.4%).
    """
    spread_as_pct = spread_pct * 100.0
    streak_bonus = min(MICRO_CAP_WIN_STREAK_BONUS_MAX,
                       win_streak * MICRO_CAP_WIN_STREAK_BONUS_PER_WIN)
    return MICRO_CAP_COMPOUNDING_PROFIT_TARGET_BASE_PCT + spread_as_pct + streak_bonus


# MICRO-CAP COMPOUNDING MODE HELPER
# ============================================================================

def get_adaptive_profit_target(win_streak: int = 0, volatility_factor: float = 1.0) -> float:
    """
    Compute an adaptive profit target for micro-cap compounding mode.

    The target starts at the base (1.2%) and scales UP during favourable
    conditions — it never drops below the base target.

    Scaling rules:
      - +MICRO_CAP_ADAPTIVE_PROFIT_WIN_STREAK_SCALE % per consecutive winning trade
      - ×volatility_factor when MICRO_CAP_ADAPTIVE_PROFIT_VOLATILITY_SCALE is True
      - Clamped to [MICRO_CAP_ADAPTIVE_PROFIT_MIN_PCT, MICRO_CAP_ADAPTIVE_PROFIT_MAX_PCT]

    Args:
        win_streak:        Number of consecutive winning trades (0 = no streak).
        volatility_factor: Market volatility multiplier (1.0 = normal; >1 = elevated).

    Returns:
        Adaptive profit target percentage (e.g. 1.2 means 1.2%).
    """
    if not MICRO_CAP_ADAPTIVE_PROFIT_SCALING:
        return MICRO_CAP_ADAPTIVE_PROFIT_MIN_PCT

    target = MICRO_CAP_ADAPTIVE_PROFIT_MIN_PCT + (win_streak * MICRO_CAP_ADAPTIVE_PROFIT_WIN_STREAK_SCALE)

    if MICRO_CAP_ADAPTIVE_PROFIT_VOLATILITY_SCALE and volatility_factor > 1.0:
        # Scale only the excess above the floor so win-streak gains are preserved:
        # new_target = target + excess * (volatility_factor - 1.0)
        excess = target - MICRO_CAP_ADAPTIVE_PROFIT_MIN_PCT
        target = target + excess * (volatility_factor - 1.0)

    target = min(target, MICRO_CAP_ADAPTIVE_PROFIT_MAX_PCT)
    target = max(target, MICRO_CAP_ADAPTIVE_PROFIT_MIN_PCT)

    logger.debug(
        f"Adaptive profit target: {target:.2f}% "
        f"(win_streak={win_streak}, volatility_factor={volatility_factor:.2f})"
    )
    return target


def get_micro_cap_compounding_config(balance: float) -> Optional[Dict[str, Union[bool, float, int]]]:
    """
    Return the micro-cap compounding mode configuration when the account
    balance is below the activation threshold ($100 by default).

    Compounding mode rules (concentrated capital — 3–5 trades per session):
      - max_positions    = 1      (one trade at a time — maximum concentration)
      - position_size    = 90%    (concentrate capital; e.g. $66 of a $74 account)
      - stop_loss        = 1.5%   (below TP1 → ≥1.67:1 R:R)
      - tp1              = 2.5%   (partial exit + trailing stop activation — was 3.0%)
      - tp2              = 3.5%   (second partial exit — was 4.5%)
      - tp3              = 6.0%   (final exit / full runner target)
      - trailing_stop_activation = 2.5%  (trailing stop kicks in at TP1)
      - trade_cooldown   = 600s   (10-min gate → up to 6 trades/hr — was 900 s)
      - adaptive_profit_scaling = True
      - profit_target    = base (2.5%) + current market spread + streak bonus
                           (computed at entry time via get_spread_adjusted_profit_target())
      - stop_loss        = 1.5%   (below base profit target → ≥1.67:1 R:R)

    The 'profit_target_pct' key in the returned dict holds the *base* target only.
    Callers must call get_spread_adjusted_profit_target(spread_pct, win_streak) at entry
    time to get the fully dynamic target.  win_streak must be reset to 0 after any losing
    trade so the bot does not chase extended targets when momentum has ended.

    Args:
        balance: Current account balance in USD.

    Returns:
        Dict with compounding mode parameters when active, otherwise None.
    """
    if balance < MICRO_CAP_COMPOUNDING_BALANCE_THRESHOLD:
        config = {
            'micro_cap_compounding_active': True,
            'balance_threshold': MICRO_CAP_COMPOUNDING_BALANCE_THRESHOLD,
            'max_positions': MICRO_CAP_COMPOUNDING_MAX_POSITIONS,
            'position_size_pct': MICRO_CAP_COMPOUNDING_POSITION_SIZE_PCT,
            'profit_target_pct': MICRO_CAP_COMPOUNDING_PROFIT_TARGET_BASE_PCT,
            'tp1_pct': MICRO_CAP_TP1_PCT,
            'tp2_pct': MICRO_CAP_TP2_PCT,
            'tp3_pct': MICRO_CAP_TP3_PCT,
            'trailing_stop_activation_pct': MICRO_CAP_TRAILING_STOP_ACTIVATION_PCT,
            'stop_loss_pct': MICRO_CAP_COMPOUNDING_STOP_LOSS_PCT,
            'trade_cooldown': MICRO_CAP_TRADE_COOLDOWN,
            'adaptive_profit_scaling': MICRO_CAP_ADAPTIVE_PROFIT_SCALING,
            'adaptive_profit_min_pct': MICRO_CAP_ADAPTIVE_PROFIT_MIN_PCT,
            'adaptive_profit_max_pct': MICRO_CAP_ADAPTIVE_PROFIT_MAX_PCT,
            'adaptive_profit_win_streak_scale': MICRO_CAP_ADAPTIVE_PROFIT_WIN_STREAK_SCALE,
            'adaptive_profit_volatility_scale': MICRO_CAP_ADAPTIVE_PROFIT_VOLATILITY_SCALE,
        }
        logger.info(
            f"🚀 Micro-cap compounding mode ACTIVE "
            f"(balance ${balance:.2f} < ${MICRO_CAP_COMPOUNDING_BALANCE_THRESHOLD:.0f}): "
            f"max_positions={MICRO_CAP_COMPOUNDING_MAX_POSITIONS}, "
            f"position_size={MICRO_CAP_COMPOUNDING_POSITION_SIZE_PCT}%, "
            f"stop_loss={MICRO_CAP_COMPOUNDING_STOP_LOSS_PCT}%, "
            f"tp1={MICRO_CAP_TP1_PCT}%, tp2={MICRO_CAP_TP2_PCT}%, tp3={MICRO_CAP_TP3_PCT}%, "
            f"trailing_stop_activation={MICRO_CAP_TRAILING_STOP_ACTIVATION_PCT}%, "
            f"profit_target=base {MICRO_CAP_COMPOUNDING_PROFIT_TARGET_BASE_PCT}% + spread + streak_bonus (dynamic), "
            f"cooldown={MICRO_CAP_TRADE_COOLDOWN}s"
        )
        return config

    return None


# ============================================================================
# DYNAMIC SCALING BASED ON EQUITY
# ============================================================================
#
# Position-size percentage tiers and max-positions unlock tiers are the
# single-source-of-truth values defined in smart_scaling_engine.py.
# Import them here so the rest of this module (and any callers) can
# reference the constants without duplicating them.

try:
    from bot.smart_scaling_engine import (
        POSITION_SIZE_TIER_MICRO   as POSITION_SIZE_PCT_TIER_MICRO,
        POSITION_SIZE_TIER_SMALL   as POSITION_SIZE_PCT_TIER_SMALL,
        POSITION_SIZE_TIER_MID     as POSITION_SIZE_PCT_TIER_MID,
        POSITION_SIZE_TIER_GROWTH  as POSITION_SIZE_PCT_TIER_GROWTH,
        POSITION_SIZE_TIER_ELITE   as POSITION_SIZE_PCT_TIER_ELITE,
        POS_UNLOCK_TIER_4,
        POS_UNLOCK_TIER_5,
        POS_UNLOCK_TIER_6,
        BASE_MAX_POSITIONS,
    )
    # Convert fractional values (0.30) to percentage values (30.0) for
    # backward-compat callers that expect percentages.
    POSITION_SIZE_PCT_TIER_MICRO  = POSITION_SIZE_PCT_TIER_MICRO  * 100
    POSITION_SIZE_PCT_TIER_SMALL  = POSITION_SIZE_PCT_TIER_SMALL  * 100
    POSITION_SIZE_PCT_TIER_MID    = POSITION_SIZE_PCT_TIER_MID    * 100
    POSITION_SIZE_PCT_TIER_GROWTH = POSITION_SIZE_PCT_TIER_GROWTH * 100
    POSITION_SIZE_PCT_TIER_ELITE  = POSITION_SIZE_PCT_TIER_ELITE  * 100
except ImportError as _import_err:
    logger.warning("smart_scaling_engine unavailable – using inline tier constants: %s", _import_err)
    POSITION_SIZE_PCT_TIER_MICRO   = 30.0
    POSITION_SIZE_PCT_TIER_SMALL   = 25.0
    POSITION_SIZE_PCT_TIER_MID     = 22.0
    POSITION_SIZE_PCT_TIER_GROWTH  = 20.0
    POSITION_SIZE_PCT_TIER_ELITE   = 18.0
    POS_UNLOCK_TIER_4              = 150.0
    POS_UNLOCK_TIER_5              = 300.0
    POS_UNLOCK_TIER_6              = 600.0
    BASE_MAX_POSITIONS             = 3


def get_position_size_pct(equity: float) -> float:
    """
    Return the recommended position-size percentage for the given equity level.

    Values are sourced from smart_scaling_engine.POSITION_SIZE_TIER_* constants
    (single source of truth):
      <$100   → 30 %  (aggressive early compounding)
      <$250   → 25 %
      <$500   → 22 %
      <$1000  → 20 %
      $1000+  → 18 %

    Args:
        equity: Current account balance in USD.

    Returns:
        Position size as a percentage of deployable capital (e.g. 25.0 = 25 %).
    """
    if equity < 100.0:
        return POSITION_SIZE_PCT_TIER_MICRO
    if equity < 250.0:
        return POSITION_SIZE_PCT_TIER_SMALL
    if equity < 500.0:
        return POSITION_SIZE_PCT_TIER_MID
    if equity < 1000.0:
        return POSITION_SIZE_PCT_TIER_GROWTH
    return POSITION_SIZE_PCT_TIER_ELITE


def get_dynamic_config(equity: float) -> Dict:
    """
    Get configuration that scales dynamically based on account equity.

    Uses the SmartScalingEngine tiers (March 2026) for both
    ``position_size_pct`` and ``max_positions``.

    Args:
        equity: Current account equity/balance

    Returns:
        Dict with dynamically adjusted configuration values
    """
    config = {
        'max_positions': MAX_POSITIONS,
        'risk_per_trade': RISK_PER_TRADE,
        'leverage_enabled': LEVERAGE_ENABLED,
    }

    # Micro-cap compounding mode: balance < $100
    # Takes full precedence over all other tiers.
    compounding = get_micro_cap_compounding_config(equity)
    if compounding:
        config['max_positions'] = compounding['max_positions']
        config['position_size_pct'] = compounding['position_size_pct']
        config['profit_target_pct'] = compounding['profit_target_pct']
        config['stop_loss_pct'] = compounding['stop_loss_pct']
        config['micro_cap_compounding_active'] = True
        return config

    # ── Position-size percentage (March 2026 tiers) ────────────────────────
    config['position_size_pct'] = get_position_size_pct(equity)

    # ── Max-positions auto-unlock (March 2026 tiers) ───────────────────────
    # Delegate to SmartScalingEngine when available; fall back to inline logic.
    try:
        from bot.smart_scaling_engine import get_smart_scaling_engine
        config['max_positions'] = get_smart_scaling_engine().get_max_positions(equity)
    except ImportError as exc:
        logger.warning("SmartScalingEngine unavailable – using inline position unlock: %s", exc)
        if equity >= POS_UNLOCK_TIER_6:
            config['max_positions'] = 6
        elif equity >= POS_UNLOCK_TIER_5:
            config['max_positions'] = 5
        elif equity >= POS_UNLOCK_TIER_4:
            config['max_positions'] = 4
        else:
            config['max_positions'] = BASE_MAX_POSITIONS

    # ── Leverage unlock at $1000 ───────────────────────────────────────────
    if equity >= 1000.0:
        config['risk_per_trade']   = 5.0
        config['leverage_enabled'] = True

    logger.info(
        "Equity $%.2f → position_size_pct=%.0f%% max_positions=%d leverage=%s",
        equity,
        config['position_size_pct'],
        config['max_positions'],
        config['leverage_enabled'],
    )

    config['micro_cap_compounding_active'] = False
    return config

# ============================================================================
# LOGGING AND DIAGNOSTICS
# ============================================================================

LOG_SIGNAL_REJECTIONS = True  # Log why signals were rejected
LOG_ENTRY_BLOCK_REASONS = True  # Log why entries were blocked

# ============================================================================
# STATE MANAGEMENT
# ============================================================================

RESET_STRATEGY_STATE = True  # Reset strategy state on startup
CLEAR_ENTRY_BLOCKS = True  # Clear entry blocks on startup
FLUSH_CACHED_BALANCES = True  # Flush cached balances on startup

# ============================================================================
# ADVANCED OPTIMIZATION SYSTEM (Jan 30, 2026)
# ============================================================================

# Enable advanced trading optimizations
ENABLE_ADVANCED_OPTIMIZER = True  # Master switch for optimization system

# Signal Scoring & Ranking
ENABLE_SIGNAL_SCORING = True  # Optimize and rank entry signals
MIN_SIGNAL_SCORE = 55.0  # Minimum score to trade (0-100) — was 60, lowered for more quality setups
MIN_SIGNAL_CONFIDENCE = 0.55  # Minimum confidence (0-1) — was 0.60

# Dynamic Volatility-Based Sizing
ENABLE_VOLATILITY_SIZING = True  # Adjust sizes based on volatility
VOLATILITY_LOOKBACK = 14  # Periods for ATR calculation
MAX_VOLATILITY_ADJUSTMENT = 0.50  # Max size reduction (50%)

# Adaptive Drawdown Control
ENABLE_DRAWDOWN_PROTECTION = True  # Protect capital during drawdowns
DRAWDOWN_CAUTION_THRESHOLD = 5.0  # % drawdown to start reducing
DRAWDOWN_HALT_THRESHOLD = 20.0  # % drawdown to halt trading

# Smart Compounding Logic
ENABLE_PROFIT_COMPOUNDING = True  # Automatically compound profits
COMPOUNDING_STRATEGY = "moderate"  # conservative/moderate/aggressive
PROFIT_REINVEST_PCT = 90.0  # % of profits to reinvest (90% for micro capital)
MIN_PROFIT_TO_COMPOUND = 5.0  # Minimum profit to trigger compounding

# ============================================================================
# MICRO-CAP COMPOUNDING MODE (balance < $100)
# ============================================================================
# Activated automatically when account balance falls below the threshold.
# Designed for faster compounding on very small balances by concentrating
# capital into a single high-conviction position with tight risk controls.
#
# Design requirements:
#   - max_positions = 1   (focus on one trade at a time)
#   - position_size = 25% of capital per trade
#   - profit_target = base_target (1.0%) + current market spread  (dynamic)
#   - stop_loss = 0.6%      (tight stop, 2:1 reward-to-risk vs base target)
#
# Note: constants are defined earlier in this file; these lines reference them
# to avoid accidental duplication divergence.
# MICRO_CAP_COMPOUNDING_BALANCE_THRESHOLD, MICRO_CAP_COMPOUNDING_MAX_POSITIONS,
# MICRO_CAP_COMPOUNDING_POSITION_SIZE_PCT, MICRO_CAP_COMPOUNDING_PROFIT_TARGET_BASE_PCT,
# MICRO_CAP_COMPOUNDING_PROFIT_TARGET_PCT, MICRO_CAP_COMPOUNDING_STOP_LOSS_PCT

# ============================================================================
# COMPLETE CONFIGURATION DICTIONARY
# ============================================================================

MICRO_CAPITAL_CONFIG = {
    # Operational mode
    'micro_capital_mode': MICRO_CAPITAL_MODE,
    'mode': MODE,
    'primary_broker': PRIMARY_BROKER,
    'secondary_broker': SECONDARY_BROKER,
    
    # Trading settings
    'live_trading': LIVE_TRADING,
    'pro_mode': PRO_MODE,
    'trading_mode': TRADING_MODE,
    
    # Balance requirements
    'min_balance_to_trade': MIN_BALANCE_TO_TRADE,
    'min_trade_size': MIN_TRADE_SIZE,
    
    # Position management
    'max_positions': MAX_POSITIONS,
    'max_position_pct': MAX_POSITION_PCT,
    'risk_per_trade': RISK_PER_TRADE,
    'enable_dca': ENABLE_DCA,  # ADDED: Feb 17, 2026
    'allow_multiple_entries_same_symbol': ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL,  # ADDED: Feb 17, 2026
    
    # Risk management
    'daily_max_loss': DAILY_MAX_LOSS,
    'max_drawdown': MAX_DRAWDOWN,
    'position_sizer': POSITION_SIZER,
    'kelly_weight': KELLY_WEIGHT,
    'volatility_weight': VOLATILITY_WEIGHT,
    'equity_weight': EQUITY_WEIGHT,
    
    # Signal filtering
    'min_signal_score': MIN_SIGNAL_SCORE,
    'min_ai_confidence': MIN_AI_CONFIDENCE,
    'min_risk_reward': MIN_RISK_REWARD,
    
    # Trading pairs
    'trade_only': TRADE_ONLY,
    
    # Advanced features
    'market_regime_engine': MARKET_REGIME_ENGINE,
    'signal_ensemble': SIGNAL_ENSEMBLE,
    'ai_trade_filter': AI_TRADE_FILTER,
    
    # Leverage and arbitrage
    'leverage_enabled': LEVERAGE_ENABLED,
    'arbitrage': ARBITRAGE,
    
    # Safety
    'auto_shutoff_on_errors': AUTO_SHUTOFF_ON_ERRORS,
    'max_consecutive_losses': MAX_CONSECUTIVE_LOSSES,
    
    # Capital allocation
    'force_cash_buffer': FORCE_CASH_BUFFER,
    
    # Exchange settings
    'exchange_priority': EXCHANGE_PRIORITY,
    'min_balance_kraken': MIN_BALANCE_KRAKEN,
    # 'min_balance_coinbase': MIN_BALANCE_COINBASE,  # Coinbase disabled
    
    # Logging
    'log_signal_rejections': LOG_SIGNAL_REJECTIONS,
    'log_entry_block_reasons': LOG_ENTRY_BLOCK_REASONS,
    
    # State management
    'reset_strategy_state': RESET_STRATEGY_STATE,
    'clear_entry_blocks': CLEAR_ENTRY_BLOCKS,
    'flush_cached_balances': FLUSH_CACHED_BALANCES,
    
    # Advanced Optimization System (Jan 30, 2026)
    'enable_advanced_optimizer': ENABLE_ADVANCED_OPTIMIZER,
    'enable_signal_scoring': ENABLE_SIGNAL_SCORING,
    'min_signal_score': MIN_SIGNAL_SCORE,
    'min_signal_confidence': MIN_SIGNAL_CONFIDENCE,
    'enable_volatility_sizing': ENABLE_VOLATILITY_SIZING,
    'volatility_lookback': VOLATILITY_LOOKBACK,
    'max_volatility_adjustment': MAX_VOLATILITY_ADJUSTMENT,
    'enable_drawdown_protection': ENABLE_DRAWDOWN_PROTECTION,
    'drawdown_caution_threshold': DRAWDOWN_CAUTION_THRESHOLD,
    'drawdown_halt_threshold': DRAWDOWN_HALT_THRESHOLD,
    'enable_profit_compounding': ENABLE_PROFIT_COMPOUNDING,
    'compounding_strategy': COMPOUNDING_STRATEGY,
    'profit_reinvest_pct': PROFIT_REINVEST_PCT,
    'min_profit_to_compound': MIN_PROFIT_TO_COMPOUND,

    # Micro-cap compounding mode (balance < $100)
    'micro_cap_compounding_balance_threshold': MICRO_CAP_COMPOUNDING_BALANCE_THRESHOLD,
    'micro_cap_compounding_max_positions': MICRO_CAP_COMPOUNDING_MAX_POSITIONS,
    'micro_cap_compounding_position_size_pct': MICRO_CAP_COMPOUNDING_POSITION_SIZE_PCT,
    'micro_cap_compounding_profit_target_pct': MICRO_CAP_COMPOUNDING_PROFIT_TARGET_PCT,
    'micro_cap_compounding_stop_loss_pct': MICRO_CAP_COMPOUNDING_STOP_LOSS_PCT,
    'micro_cap_trade_cooldown': MICRO_CAP_TRADE_COOLDOWN,
    'micro_cap_tp1_pct': MICRO_CAP_TP1_PCT,
    'micro_cap_tp2_pct': MICRO_CAP_TP2_PCT,
    'micro_cap_tp3_pct': MICRO_CAP_TP3_PCT,
    'micro_cap_trailing_stop_activation_pct': MICRO_CAP_TRAILING_STOP_ACTIVATION_PCT,

    # Adaptive Profit Scaling (micro-cap compounding mode)
    'micro_cap_adaptive_profit_scaling': MICRO_CAP_ADAPTIVE_PROFIT_SCALING,
    'micro_cap_adaptive_profit_min_pct': MICRO_CAP_ADAPTIVE_PROFIT_MIN_PCT,
    'micro_cap_adaptive_profit_max_pct': MICRO_CAP_ADAPTIVE_PROFIT_MAX_PCT,
    'micro_cap_adaptive_profit_win_streak_scale': MICRO_CAP_ADAPTIVE_PROFIT_WIN_STREAK_SCALE,
    'micro_cap_adaptive_profit_volatility_scale': MICRO_CAP_ADAPTIVE_PROFIT_VOLATILITY_SCALE,
}

# ============================================================================
# ENVIRONMENT VARIABLE MAPPING
# ============================================================================

def get_environment_variables(equity: Optional[float] = None) -> Dict[str, str]:
    """
    Get environment variables for micro capital mode.
    
    Args:
        equity: Current account equity for dynamic scaling (optional)
        
    Returns:
        Dict of environment variable names and values
    """
    # Get dynamic config if equity provided
    dynamic_config = get_dynamic_config(equity) if equity else {}
    
    # Base environment variables
    env_vars = {
        'MICRO_CAPITAL_MODE': str(MICRO_CAPITAL_MODE).lower(),
        'MODE': MODE,
        'PRIMARY_BROKER': PRIMARY_BROKER,
        'SECONDARY_BROKER': SECONDARY_BROKER,
        
        'LIVE_TRADING': '1' if LIVE_TRADING else '0',
        'PRO_MODE': str(PRO_MODE).lower(),
        'TRADING_MODE': TRADING_MODE,
        
        'MINIMUM_TRADING_BALANCE': str(MIN_BALANCE_TO_TRADE),
        'MIN_CASH_TO_BUY': str(MIN_TRADE_SIZE),
        
        'MAX_CONCURRENT_POSITIONS': str(dynamic_config.get('max_positions', MAX_POSITIONS)),
        'MAX_POSITION_PCT': str(MAX_POSITION_PCT),
        'RISK_PER_TRADE': str(dynamic_config.get('risk_per_trade', RISK_PER_TRADE)),
        'ENABLE_DCA': str(ENABLE_DCA).lower(),  # ADDED: Feb 17, 2026
        'ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL': str(ALLOW_MULTIPLE_ENTRIES_SAME_SYMBOL).lower(),  # ADDED: Feb 17, 2026
        
        'DAILY_MAX_LOSS': str(DAILY_MAX_LOSS),
        'MAX_DRAWDOWN': str(MAX_DRAWDOWN),
        'POSITION_SIZER': POSITION_SIZER,
        
        'MIN_SIGNAL_SCORE': str(MIN_SIGNAL_SCORE),
        'MIN_AI_CONFIDENCE': str(MIN_AI_CONFIDENCE),
        'MIN_RISK_REWARD': str(MIN_RISK_REWARD),
        
        'TRADE_ONLY': ','.join(TRADE_ONLY),
        
        'MARKET_REGIME_ENGINE': str(MARKET_REGIME_ENGINE).lower(),
        'SIGNAL_ENSEMBLE': str(SIGNAL_ENSEMBLE).lower(),
        'AI_TRADE_FILTER': str(AI_TRADE_FILTER).lower(),
        
        'LEVERAGE_ENABLED': str(dynamic_config.get('leverage_enabled', LEVERAGE_ENABLED)).lower(),
        'ARBITRAGE': str(ARBITRAGE).lower(),
        
        'AUTO_SHUTOFF_ON_ERRORS': str(AUTO_SHUTOFF_ON_ERRORS).lower(),
        'MAX_CONSECUTIVE_LOSSES': str(MAX_CONSECUTIVE_LOSSES),
        
        'FORCE_CASH_BUFFER': str(FORCE_CASH_BUFFER),
        
        'EXCHANGE_PRIORITY': ','.join(EXCHANGE_PRIORITY),
        'MIN_BALANCE_KRAKEN': str(MIN_BALANCE_KRAKEN),
        # 'MIN_BALANCE_COINBASE': str(MIN_BALANCE_COINBASE),  # Coinbase disabled
        
        'LOG_SIGNAL_REJECTIONS': str(LOG_SIGNAL_REJECTIONS).lower(),
        'LOG_ENTRY_BLOCK_REASONS': str(LOG_ENTRY_BLOCK_REASONS).lower(),
        
        'RESET_STRATEGY_STATE': str(RESET_STRATEGY_STATE).lower(),
        'CLEAR_ENTRY_BLOCKS': str(CLEAR_ENTRY_BLOCKS).lower(),
        'FLUSH_CACHED_BALANCES': str(FLUSH_CACHED_BALANCES).lower(),
    }
    
    return env_vars


def apply_micro_capital_config(equity: Optional[float] = None, set_env_vars: bool = True) -> Dict:
    """
    Apply micro capital configuration.
    
    Args:
        equity: Current account equity for dynamic scaling (optional)
        set_env_vars: If True, sets environment variables. If False, only returns config.
        
    Returns:
        Dict with all configuration values and dynamic adjustments
    """
    # Get environment variables
    env_vars = get_environment_variables(equity)
    
    # Optionally set environment variables
    if set_env_vars:
        for key, value in env_vars.items():
            os.environ[key] = value
            logger.debug(f"Set {key} = {value}")
    
    # Get dynamic config if equity provided
    dynamic_config = get_dynamic_config(equity) if equity else {}
    
    # Return complete configuration
    return {
        'base_config': MICRO_CAPITAL_CONFIG,
        'dynamic_config': dynamic_config,
        'environment_variables': env_vars,
        'current_equity': equity,
    }


def get_config_summary(equity: Optional[float] = None) -> str:
    """
    Get human-readable summary of micro capital configuration.
    
    Args:
        equity: Current account equity for dynamic scaling display
        
    Returns:
        Formatted configuration summary
    """
    dynamic_config = get_dynamic_config(equity) if equity else {}

    max_positions = dynamic_config.get('max_positions', MAX_POSITIONS)
    risk_per_trade = dynamic_config.get('risk_per_trade', RISK_PER_TRADE)
    leverage_enabled = dynamic_config.get('leverage_enabled', LEVERAGE_ENABLED)
    compounding_active = dynamic_config.get('micro_cap_compounding_active', False)

    equity_str = f"${equity:.2f}" if equity is not None else "$0.00"

    compounding_section = ""
    if compounding_active:
        adaptive_label = "ON" if MICRO_CAP_ADAPTIVE_PROFIT_SCALING else "OFF"
        compounding_section = f"""
🚀 MICRO-CAP COMPOUNDING MODE (balance < ${MICRO_CAP_COMPOUNDING_BALANCE_THRESHOLD:.0f}):
   • Max Positions:          {MICRO_CAP_COMPOUNDING_MAX_POSITIONS}  (single position focus)
   • Position Size:          {MICRO_CAP_COMPOUNDING_POSITION_SIZE_PCT:.0f}% of capital per trade
   • Stop Loss:              {MICRO_CAP_COMPOUNDING_STOP_LOSS_PCT:.1f}%  (2:1 reward-to-risk)
   • Target 1 (TP1):         {MICRO_CAP_TP1_PCT:.1f}%  (partial exit + trailing stop activation)
   • Target 2 (TP2):         {MICRO_CAP_TP2_PCT:.1f}%  (second partial exit)
   • Target 3 (TP3):         {MICRO_CAP_TP3_PCT:.1f}%  (final exit / runner target)
   • Trailing Stop:          activates after {MICRO_CAP_TRAILING_STOP_ACTIVATION_PCT:.1f}% profit (TP1)
   • Trade Cooldown:         {MICRO_CAP_TRADE_COOLDOWN}s per symbol  (theoretical max ~{3600 // MICRO_CAP_TRADE_COOLDOWN} re-entries/hr per symbol)
   • Adaptive Profit Scaling:{adaptive_label}  [{MICRO_CAP_ADAPTIVE_PROFIT_MIN_PCT:.1f}% – {MICRO_CAP_ADAPTIVE_PROFIT_MAX_PCT:.1f}%]
   • Adaptive Base Target:   {MICRO_CAP_COMPOUNDING_PROFIT_TARGET_BASE_PCT:.1f}% (base) + spread + streak bonus (used for dynamic scaling only)
"""

    return f"""
╔══════════════════════════════════════════════════════════════════════════╗
║                  NIJA MICRO CAPITAL MODE CONFIGURATION                   ║
║                         Version 1.0                                       ║
╚══════════════════════════════════════════════════════════════════════════╝

📊 CURRENT EQUITY: {equity_str}
{compounding_section}
⚙️  OPERATIONAL MODE:
   • Mode: {MODE}
   • Micro Capital Mode: {MICRO_CAPITAL_MODE}
   • Primary Broker: {PRIMARY_BROKER}
   • Secondary Broker: {SECONDARY_BROKER if SECONDARY_BROKER else 'None (Coinbase disabled)'}
   • Live Trading: {LIVE_TRADING}
   • PRO Mode: {PRO_MODE}

💰 BALANCE REQUIREMENTS:
   • Minimum Balance to Trade: ${MIN_BALANCE_TO_TRADE:.2f}
   • Minimum Trade Size: ${MIN_TRADE_SIZE:.2f}
   • Minimum Balance (Kraken): ${MIN_BALANCE_KRAKEN:.2f}

📈 POSITION MANAGEMENT:
   • Max Concurrent Positions: {max_positions}
   • Max Position Size: {MAX_POSITION_PCT:.1f}% of capital
   • Risk Per Trade: {risk_per_trade:.1f}%
   • Position Sizer: {POSITION_SIZER}

🛡️  RISK MANAGEMENT:
   • Daily Max Loss: {DAILY_MAX_LOSS:.1f}%
   • Max Drawdown: {MAX_DRAWDOWN:.1f}%
   • Kelly Weight: {KELLY_WEIGHT:.0%}
   • Volatility Weight: {VOLATILITY_WEIGHT:.0%}
   • Equity Weight: {EQUITY_WEIGHT:.0%}

🎯 SIGNAL FILTERING:
   • Min Signal Score: {MIN_SIGNAL_SCORE:.0%}
   • Min AI Confidence: {MIN_AI_CONFIDENCE:.0%}
   • Min Risk/Reward: {MIN_RISK_REWARD:.1f}

💱 TRADING PAIRS:
   • Allowed: {', '.join(TRADE_ONLY)}
   • Exchange Priority: {' > '.join(EXCHANGE_PRIORITY)}

🔥 ADVANCED FEATURES:
   • Market Regime Engine: {MARKET_REGIME_ENGINE}
   • Signal Ensemble: {SIGNAL_ENSEMBLE}
   • AI Trade Filter: {AI_TRADE_FILTER}
   • Trading Mode: {TRADING_MODE}
   • Leverage: {leverage_enabled} {'(auto-enabled at $1000+)' if not leverage_enabled and equity and equity < 1000 else ''}
   • Arbitrage: {ARBITRAGE}

🚨 SAFETY FEATURES:
   • Auto-Shutoff on Errors: {AUTO_SHUTOFF_ON_ERRORS}
   • Max Consecutive Losses: {MAX_CONSECUTIVE_LOSSES}
   • Cash Buffer: {FORCE_CASH_BUFFER:.1f}%

📊 DYNAMIC SCALING THRESHOLDS:
   • <${MICRO_CAP_COMPOUNDING_BALANCE_THRESHOLD:.0f}: Micro-cap compounding mode (1 position, {MICRO_CAP_COMPOUNDING_POSITION_SIZE_PCT:.0f}% size, PT={MICRO_CAP_COMPOUNDING_PROFIT_TARGET_BASE_PCT:.1f}%+spread+streak, SL={MICRO_CAP_COMPOUNDING_STOP_LOSS_PCT:.1f}%)
   • $250+: 3 positions, 4% risk per trade
   • $500+: 4 positions
   • $1000+: 6 positions, 5% risk, leverage enabled

📝 LOGGING:
   • Log Signal Rejections: {LOG_SIGNAL_REJECTIONS}
   • Log Entry Block Reasons: {LOG_ENTRY_BLOCK_REASONS}

🔄 STATE MANAGEMENT:
   • Reset Strategy State: {RESET_STRATEGY_STATE}
   • Clear Entry Blocks: {CLEAR_ENTRY_BLOCKS}
   • Flush Cached Balances: {FLUSH_CACHED_BALANCES}

═══════════════════════════════════════════════════════════════════════════

This configuration is optimized for:
✅ Micro capital accounts ($15-$500)
✅ Conservative risk management
✅ Dynamic scaling as equity grows
✅ Multi-broker support
✅ Advanced AI and signal filtering
✅ Automatic feature enablement
✅ Micro-cap compounding mode for fast growth under $100

To activate: apply_micro_capital_config(equity=your_balance)
"""


if __name__ == "__main__":
    # Print configuration summary at different equity levels
    print("="*80)
    print("MICRO CAPITAL MODE CONFIGURATION - DEMO")
    print("="*80)
    
    print("\n" + "="*80)
    print("STARTING ACCOUNT ($15)")
    print("="*80)
    print(get_config_summary(equity=15.0))
    
    print("\n" + "="*80)
    print("SCALED ACCOUNT ($250)")
    print("="*80)
    print(get_config_summary(equity=250.0))
    
    print("\n" + "="*80)
    print("COPY TRADING ENABLED ($500)")
    print("="*80)
    print(get_config_summary(equity=500.0))
    
    print("\n" + "="*80)
    print("FULL FEATURES ($1000)")
    print("="*80)
    print(get_config_summary(equity=1000.0))
    
    print("\n" + "="*80)
    print("APPLYING CONFIGURATION")
    print("="*80)
    config = apply_micro_capital_config(equity=100.0, set_env_vars=False)
    print(f"✅ Configuration applied successfully!")
    print(f"   Base Config Keys: {len(config['base_config'])}")
    print(f"   Dynamic Config: {config['dynamic_config']}")
    print(f"   Environment Variables: {len(config['environment_variables'])}")
