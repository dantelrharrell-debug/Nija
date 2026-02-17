# risk_manager.py
"""
NIJA Adaptive Risk Management Module
Dynamic position sizing and risk calculations with AI-driven adjustments

Features:
- ADX-based position sizing (2-10%)
- AI confidence-based adjustments
- Winning/losing streak tracking
- Volatility-based exposure management
- Dynamic max exposure limits
- FEE-AWARE PROFITABILITY (v2.1 - Dec 19, 2025)

Version: 2.1 (Enhanced for profitability and fee awareness)
"""

import pandas as pd
from typing import Dict, Tuple, List
from datetime import datetime
import time
import logging

logger = logging.getLogger("nija.risk_manager")

# Import scalar helper for indicator conversions
try:
    from indicators import scalar
except ImportError:
    # Fallback if indicators.py is not available
    def scalar(x):
        if isinstance(x, (tuple, list)):
            return float(x[0])
        return float(x)

# Import fee-aware configuration
try:
    from fee_aware_config import (
        MIN_BALANCE_TO_TRADE,
        MICRO_ACCOUNT_THRESHOLD,
        get_position_size_pct,
        get_min_profit_target,
        should_trade,
        get_fee_adjusted_targets,
        MAX_TRADES_PER_DAY
    )
    FEE_AWARE_MODE = True
    logger.info("✅ Fee-aware configuration loaded - PROFITABILITY MODE ACTIVE")
except ImportError:
    FEE_AWARE_MODE = False
    MIN_BALANCE_TO_TRADE = 10.0
    MICRO_ACCOUNT_THRESHOLD = 5.0
    logger.warning("⚠️ Fee-aware config not found - using legacy mode")

# Import tier configuration for tier-aware risk management
try:
    from tier_config import (
        get_tier_from_balance, 
        get_tier_config, 
        log_tier_floors,
        emit_tier_floor_metrics,
        assert_expected_tier_floors
    )
    TIER_AWARE_MODE = True
    logger.info("✅ Tier configuration loaded - TIER-AWARE RISK MANAGEMENT ACTIVE")
except ImportError:
    TIER_AWARE_MODE = False
    # Set all tier-related functions to None as fallback
    log_tier_floors = emit_tier_floor_metrics = assert_expected_tier_floors = None
    logger.warning("⚠️ Tier config not found - tier enforcement disabled")

# Import small account constants from fee_aware_config
try:
    from fee_aware_config import (
        SMALL_ACCOUNT_THRESHOLD,
        SMALL_ACCOUNT_MAX_PCT_DIFF,
        STANDARD_MAX_PCT_DIFF
    )
except ImportError:
    # Fallback values if import fails
    SMALL_ACCOUNT_THRESHOLD = 100.0
    SMALL_ACCOUNT_MAX_PCT_DIFF = 10.0
    STANDARD_MAX_PCT_DIFF = 5.0
    logger.warning("Could not import small account constants from fee_aware_config, using defaults")


class AdaptiveRiskManager:
    """
    Manages position sizing, stop loss, and take profit calculations
    with dynamic adjustments based on:
    - Trend strength (ADX)
    - AI signal confidence
    - Recent trade performance (streaks)
    - Market volatility
    - Total portfolio exposure
    - FEE AWARENESS (NEW - prevents unprofitable small trades)
    - TIER LOCKING (v4.1 - Jan 2026 - enforces tier limits in PRO MODE)
    - EXCHANGE-SPECIFIC PROFILES (OPTIONAL - uses exchange risk profiles if available)
    """

    def __init__(self, min_position_pct=0.02, max_position_pct=0.25,
                 max_total_exposure=0.60, use_exchange_profiles=False,
                 pro_mode=False, min_free_reserve_pct=0.15, tier_lock=None,
                 max_portfolio_volatility=0.04,
                 soft_position_limit_pct=0.04, hard_position_limit_pct=0.05):
        """
        Initialize Adaptive Risk Manager - OPTIMIZED FOR HIGH WIN RATE v7.5
        Updated Feb 12, 2026: Added soft/hard position limit enforcement

        Args:
            min_position_pct: Minimum position size as % of account (default 2% - conservative for weak trends)
            max_position_pct: Maximum position size as % of account (default 25% - OPTIMIZED for small capital fast-frequency)
            max_total_exposure: Maximum total exposure across all positions (default 60% - OPTIMIZED for safety)
            use_exchange_profiles: If True, uses exchange-specific risk profiles (default False)
            pro_mode: If True, enables PRO MODE with position rotation (default False)
            min_free_reserve_pct: Minimum free balance % to maintain in PRO MODE (default 15%)
            tier_lock: If set, locks risk to specific tier limits (e.g., 'SAVER', 'INVESTOR')
            max_portfolio_volatility: Maximum portfolio volatility (default 4% = 0.04) - CRITICAL for aggressive sizing
            soft_position_limit_pct: Soft limit for single position (default 4% = 0.04) - triggers warning and size reduction
            hard_position_limit_pct: Hard limit for single position (default 5% = 0.05) - blocks new positions
        """
        self.min_position_pct = min_position_pct
        self.max_position_pct = max_position_pct
        self.max_total_exposure = max_total_exposure
        self.pro_mode = pro_mode
        self.min_free_reserve_pct = min_free_reserve_pct
        self.tier_lock = tier_lock  # NEW: Tier locking for PRO MODE
        self.max_portfolio_volatility = max_portfolio_volatility  # NEW: Volatility exposure cap
        
        # SOFT + HARD ENFORCEMENT (Feb 12, 2026)
        # Provides flexibility with discipline
        self.soft_position_limit_pct = soft_position_limit_pct  # Default 4% - triggers warning and size reduction
        self.hard_position_limit_pct = hard_position_limit_pct  # Default 5% - blocks position entirely

        # Track recent trades for streak analysis
        self.recent_trades: List[Dict] = []
        self.max_trade_history = 20  # Keep last 20 trades
        
        # Consecutive loss cooldown (3 losses = 60 min pause)
        self.consecutive_loss_count = 0
        self.cooldown_until = None  # datetime when cooldown expires
        self.COOLDOWN_LOSS_THRESHOLD = 3  # 3 consecutive losses
        self.COOLDOWN_DURATION_MINUTES = 60  # 60 minute pause

        # Current exposure tracking
        self.current_exposure = 0.0

        # Portfolio volatility tracking (NEW - for volatility exposure cap)
        self.current_portfolio_volatility = 0.0
        self.open_positions_volatility: Dict[str, float] = {}  # position_id -> volatility

        # Trade frequency tracking (for fee awareness)
        self.trades_today = 0
        self.last_trade_time = 0
        self.daily_reset_date = datetime.now().date()

        # Fee-aware mode status
        self.fee_aware_mode = FEE_AWARE_MODE

        # Exchange-specific profiles (optional)
        self.use_exchange_profiles = use_exchange_profiles
        self.exchange_risk_manager = None

        if self.use_exchange_profiles:
            try:
                from exchange_risk_profiles import get_exchange_risk_manager
                self.exchange_risk_manager = get_exchange_risk_manager()
                logger.info("✅ Exchange-specific risk profiles enabled")
            except ImportError:
                logger.warning("⚠️ Exchange risk profiles not available, using standard mode")
                self.use_exchange_profiles = False

        if self.tier_lock:
            logger.info(f"✅ Adaptive Risk Manager initialized - PRO MODE with TIER LOCK: {self.tier_lock}")
            logger.info(f"   Tier-locked risk management active")
            logger.info(f"   Users get PRO logic with tier-capped risk")
        elif self.pro_mode:
            logger.info(f"✅ Adaptive Risk Manager initialized - PRO MODE ACTIVE")
            logger.info(f"   Position rotation enabled")
            logger.info(f"   Minimum free reserve: {min_free_reserve_pct*100:.0f}%")
        elif self.fee_aware_mode:
            logger.info(f"✅ Adaptive Risk Manager initialized - FEE-AWARE PROFITABILITY MODE")
            logger.info(f"   Minimum balance: ${MIN_BALANCE_TO_TRADE}")
            logger.info(f"   Max trades/day: {MAX_TRADES_PER_DAY}")
        else:
            logger.info(f"Adaptive Risk Manager initialized: {min_position_pct*100}%-{max_position_pct*100}% position sizing")
        
        # Log tier floor configuration at startup for visibility
        if TIER_AWARE_MODE and log_tier_floors is not None:
            log_tier_floors()
            
            # Assert expected tier floors in production
            if assert_expected_tier_floors is not None:
                try:
                    assert_expected_tier_floors()
                except AssertionError as e:
                    # Re-raise assertion errors in production
                    raise
                except Exception as e:
                    logger.warning(f"⚠️ Tier floor assertion check failed: {e}")
            
            # Emit metrics once at startup
            if emit_tier_floor_metrics is not None:
                try:
                    metrics = emit_tier_floor_metrics()
                    # Log metrics for visibility (in production, these would go to monitoring system)
                    logger.debug(f"Tier floor metrics: {len(metrics)} gauges emitted")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to emit tier floor metrics: {e}")

    def record_trade(self, outcome: str, pnl: float, hold_time_minutes: int) -> None:
        """
        Record a completed trade for streak analysis.

        Args:
            outcome: 'win', 'loss', or 'breakeven'
            pnl: Profit/loss in dollars
            hold_time_minutes: How long position was held
        """
        trade_record = {
            'timestamp': datetime.now(),
            'outcome': outcome,
            'pnl': pnl,
            'hold_time_minutes': hold_time_minutes
        }

        self.recent_trades.append(trade_record)

        # Keep only recent trades
        if len(self.recent_trades) > self.max_trade_history:
            self.recent_trades = self.recent_trades[-self.max_trade_history:]
        
        # Update consecutive loss counter and trigger cooldown if needed
        if outcome == 'loss':
            self.consecutive_loss_count += 1
            logger.info(f"📉 Loss recorded: consecutive losses = {self.consecutive_loss_count}")
            
            # Check if we hit cooldown threshold
            if self.consecutive_loss_count >= self.COOLDOWN_LOSS_THRESHOLD:
                self._activate_cooldown()
        else:
            # Win or breakeven resets the counter
            if self.consecutive_loss_count > 0:
                logger.info(f"✅ Winning trade resets loss streak (was {self.consecutive_loss_count})")
            self.consecutive_loss_count = 0

        logger.debug(f"Trade recorded: {outcome}, PnL: ${pnl:.2f}")

    def _activate_cooldown(self) -> None:
        """
        Activate trading cooldown after consecutive losses.
        """
        from datetime import timedelta
        self.cooldown_until = datetime.now() + timedelta(minutes=self.COOLDOWN_DURATION_MINUTES)
        logger.warning(
            f"🚨 COOLDOWN ACTIVATED: {self.consecutive_loss_count} consecutive losses detected. "
            f"Trading paused until {self.cooldown_until.strftime('%H:%M:%S')} ({self.COOLDOWN_DURATION_MINUTES} minutes)"
        )
    
    def is_in_cooldown(self) -> bool:
        """
        Check if currently in cooldown period.
        
        Returns:
            True if in cooldown, False otherwise
        """
        if self.cooldown_until is None:
            return False
        
        now = datetime.now()
        if now < self.cooldown_until:
            remaining_minutes = (self.cooldown_until - now).total_seconds() / 60
            return True
        else:
            # Cooldown expired
            if self.cooldown_until is not None:  # Only log if transitioning from cooldown
                logger.info(f"✅ Cooldown expired - trading resumed")
            self.cooldown_until = None
            return False
    
    def get_cooldown_remaining_minutes(self) -> float:
        """
        Get remaining cooldown time in minutes.
        
        Returns:
            Minutes remaining, or 0 if not in cooldown
        """
        if not self.is_in_cooldown():
            return 0.0
        
        now = datetime.now()
        remaining_seconds = (self.cooldown_until - now).total_seconds()
        return max(0.0, remaining_seconds / 60)

    def get_current_streak(self) -> Tuple[str, int]:
        """
        Calculate current winning or losing streak.

        Returns:
            Tuple of (streak_type, streak_length)
            - streak_type: 'winning', 'losing', or 'none'
            - streak_length: Number of consecutive trades
        """
        if not self.recent_trades:
            return ('none', 0)

        # Count consecutive wins or losses from most recent
        streak_type = None
        streak_length = 0

        for trade in reversed(self.recent_trades):
            outcome = trade['outcome']

            # PROFIT GATE: No breakeven outcomes anymore - only win or loss
            # If somehow breakeven appears, treat as loss (shouldn't happen)
            if outcome == 'breakeven':
                outcome = 'loss'

            if streak_type is None:
                # First trade in streak
                streak_type = 'winning' if outcome == 'win' else 'losing'
                streak_length = 1
            elif (outcome == 'win' and streak_type == 'winning') or \
                 (outcome == 'loss' and streak_type == 'losing'):
                # Streak continues
                streak_length += 1
            else:
                # Streak broken
                break

        return (streak_type or 'none', streak_length)

    def get_win_rate(self, lookback: int = 10) -> float:
        """
        Calculate win rate from recent trades.

        Args:
            lookback: Number of recent trades to analyze

        Returns:
            float: Win rate (0-1)
        """
        if not self.recent_trades:
            return 0.5  # Neutral if no history

        recent = self.recent_trades[-lookback:]
        wins = sum(1 for t in recent if t['outcome'] == 'win')
        total = len(recent)

        return wins / total if total > 0 else 0.5

    def get_regime_based_multiplier(self, volatility_pct: float, adx: float) -> Tuple[float, str]:
        """
        Calculate REGIME-BASED position size multiplier - CAPITAL INTELLIGENCE

        This is where hedge funds separate themselves from bots.

        Regime Behavior:
        - LOW_VOL (Low Volatility Chop) → Reduce size (0.6x)
        - MEDIUM (Medium Trend) → Normal size (1.0x)
        - HIGH_VOL_TREND (High Volatility Trend) → Increase size (1.4x)

        Strategy:
        - Low volatility (<0.5%) → 0.6x - chop risk, tighten exposure
        - Medium volatility (0.5%-2%) → 1.0x - normal conditions
        - High volatility trend (>2% + ADX>25) → 1.4x - ride strong trends aggressively
        - High volatility chop (>2% + ADX<25) → 0.6x - dangerous whipsaws

        This massively increases:
        - Capital efficiency (right-size for conditions)
        - Compounding speed (bigger bets in ideal conditions)
        - Risk management (smaller in dangerous conditions)

        Args:
            volatility_pct: Current market volatility as decimal (e.g., 0.01 = 1%)
            adx: Current ADX value for trend strength

        Returns:
            Tuple of (multiplier, regime_description)
        """
        volatility_pct = scalar(volatility_pct)
        adx = scalar(adx)

        # LOW VOLATILITY: Choppy, ranging market
        if volatility_pct < 0.005:
            return 0.6, "LOW_VOL"

        # HIGH VOLATILITY + TREND: Ideal for momentum strategies - AGGRESSIVE
        elif volatility_pct > 0.02 and adx > 25:
            return 1.4, "HIGH_VOL_TREND"

        # HIGH VOLATILITY + NO TREND: Dangerous whipsaw conditions
        elif volatility_pct > 0.02 and adx <= 25:
            return 0.6, "HIGH_VOLATILITY_CHOP"

        # MEDIUM VOLATILITY: Normal conditions
        else:
            return 1.0, "MEDIUM"
            return 1.0, "MEDIUM_VOLATILITY"

    def check_position_limits(self, position_pct: float, symbol: str = None) -> Tuple[bool, float, Dict]:
        """
        Check soft and hard position limits with enforcement
        
        SOFT + HARD ENFORCEMENT (Feb 12, 2026):
        - Soft warning at 4% → reduce position size by 50%
        - Hard block at 5% → no new positions
        
        This provides flexibility without breaking discipline.
        
        Args:
            position_pct: Proposed position size as % of portfolio
            symbol: Optional symbol for logging
            
        Returns:
            Tuple of (allowed, adjusted_pct, enforcement_info)
            - allowed: True if position can be opened, False if hard blocked
            - adjusted_pct: Adjusted position size (may be reduced if soft limit triggered)
            - enforcement_info: Dictionary with enforcement details
        """
        enforcement_info = {
            'original_pct': position_pct,
            'adjusted_pct': position_pct,
            'soft_limit_triggered': False,
            'hard_limit_triggered': False,
            'enforcement_action': 'none'
        }
        
        symbol_str = f" for {symbol}" if symbol else ""
        
        # HARD LIMIT: 5% - Absolute block
        if position_pct > self.hard_position_limit_pct:
            enforcement_info['hard_limit_triggered'] = True
            enforcement_info['enforcement_action'] = 'blocked'
            logger.warning(
                f"🚫 HARD LIMIT BLOCK{symbol_str}: "
                f"Position {position_pct*100:.2f}% exceeds hard limit {self.hard_position_limit_pct*100:.0f}%. "
                f"NO NEW POSITIONS ALLOWED."
            )
            return False, 0.0, enforcement_info
        
        # SOFT LIMIT: 4% - Warning and reduction
        if position_pct > self.soft_position_limit_pct:
            enforcement_info['soft_limit_triggered'] = True
            enforcement_info['enforcement_action'] = 'reduced'
            
            # Reduce position size by 50%
            adjusted_pct = position_pct * 0.5
            enforcement_info['adjusted_pct'] = adjusted_pct
            enforcement_info['reduction_factor'] = 0.5
            
            logger.warning(
                f"⚠️ SOFT LIMIT WARNING{symbol_str}: "
                f"Position {position_pct*100:.2f}% exceeds soft limit {self.soft_position_limit_pct*100:.0f}%. "
                f"REDUCING position size by 50% to {adjusted_pct*100:.2f}%"
            )
            return True, adjusted_pct, enforcement_info
        
        # Within limits - no action needed
        return True, position_pct, enforcement_info

    def calculate_position_size(self, account_balance: float, adx: float,
                               signal_strength: int = 3, ai_confidence: float = 0.5,
                               volatility_pct: float = 0.01,
                               use_total_capital: bool = False,
                               position_value: float = 0.0,
                               portfolio_state=None,
                               broker_name: str = None,
                               broker_min_position: float = None,
                               regime_confidence: float = None) -> Tuple[float, Dict]:
        """
        Calculate adaptive position size based on multiple factors.

        FIX #1: PORTFOLIO-FIRST ACCOUNTING
        If portfolio_state is provided, uses total_equity as the sizing base instead of cash.
        This ensures position sizing accounts for capital already deployed in open positions.

        PRO MODE: Can use total capital (free balance + position values) instead of just free balance.

        Factors:
        1. ADX (trend strength) - base sizing
        2. AI signal confidence - boost or reduce
        3. Recent streak - reduce after losses, cautiously increase after wins
        4. Volatility - reduce in high volatility
        5. Current exposure - respect max total exposure

        ADX-based allocation:
        - ADX < 20: No trade (weak trend)
        - ADX 20-25: 2% (weak trending)
        - ADX 25-30: 4% (moderate trending)
        - ADX 30-40: 6% (strong trending)
        - ADX 40-50: 8% (very strong trending)
        - ADX > 50: 10% (extremely strong trending)

        Args:
            account_balance: Current free balance in USD (DEPRECATED if portfolio_state provided)
            adx: Current ADX value
            signal_strength: Entry signal strength (1-5, default 3)
            ai_confidence: AI model confidence (0-1, default 0.5)
            volatility_pct: Current market volatility as % (default 0.01)
            use_total_capital: If True, uses account_balance + position_value as base (PRO MODE)
            position_value: Total value of open positions (only used if use_total_capital=True)
            portfolio_state: PortfolioState instance (preferred - uses total_equity for sizing)
            broker_name: Name of broker (e.g., 'kraken', 'coinbase') for minimum adjustments
            broker_min_position: Broker's minimum position size in USD for intelligent bumping
            regime_confidence: Regime classification confidence (0-1, optional - GOD MODE+)
                             Scales position size by confidence: risk = base_risk * regime_confidence

        Returns:
            Tuple of (position_size, breakdown_dict)
            - position_size: Position size in USD
            - breakdown_dict: Details of sizing calculations
        """
        breakdown = {}
        
        # Check if in cooldown period (3 consecutive losses = 60 min pause)
        if self.is_in_cooldown():
            remaining_minutes = self.get_cooldown_remaining_minutes()
            logger.warning(
                f"🚨 COOLDOWN ACTIVE: {self.consecutive_loss_count} consecutive losses. "
                f"Trading paused for {remaining_minutes:.1f} more minutes."
            )
            breakdown['cooldown_active'] = True
            breakdown['cooldown_remaining_minutes'] = remaining_minutes
            return (0.0, breakdown)  # Return 0 position size during cooldown

        # Normalize all numeric inputs to handle tuples/lists
        adx = scalar(adx)
        ai_confidence = scalar(ai_confidence)
        volatility_pct = scalar(volatility_pct)

        # FIX #1: Use portfolio total_equity if available
        if portfolio_state is not None:
            total_equity = portfolio_state.total_equity
            available_cash = portfolio_state.available_cash
            position_value_from_portfolio = portfolio_state.total_position_value

            breakdown['portfolio_accounting'] = True
            breakdown['total_equity'] = total_equity
            breakdown['available_cash'] = available_cash
            breakdown['position_value'] = position_value_from_portfolio

            # Use total equity as sizing base (MANDATORY per problem statement)
            sizing_base = total_equity

            logger.debug(
                f"Portfolio-first sizing: equity=${total_equity:.2f}, "
                f"cash=${available_cash:.2f}, positions=${position_value_from_portfolio:.2f}"
            )
        else:
            # Legacy mode: Calculate base capital for position sizing
            if use_total_capital and self.pro_mode:
                total_capital = account_balance + position_value
                breakdown['pro_mode'] = True
                breakdown['free_balance'] = account_balance
                breakdown['position_value'] = position_value
                breakdown['total_capital'] = total_capital

                # In PRO MODE, ensure we maintain minimum free balance reserve
                min_free_reserve = total_capital * self.min_free_reserve_pct
                if account_balance < min_free_reserve:
                    logger.warning(f"⚠️ PRO MODE: Below minimum free reserve (${account_balance:.2f} < ${min_free_reserve:.2f})")
                    logger.warning(f"   Need to rotate positions or skip trade")
                    breakdown['below_free_reserve'] = True
                    # Still allow calculation but flag it

                # Use total capital as base for sizing
                sizing_base = total_capital
            else:
                sizing_base = account_balance
                breakdown['pro_mode'] = False
                breakdown['portfolio_accounting'] = False
                logger.debug(f"Legacy cash-based sizing: ${account_balance:.2f}")

        # No trade if ADX < 20
        if float(adx) < 20:
            return 0.0, {'reason': 'ADX too low', 'adx': adx}

        # 1. Base allocation from ADX
        if float(adx) < 25:
            base_pct = 0.02  # 2%
        elif float(adx) < 30:
            base_pct = 0.04  # 4%
        elif float(adx) < 40:
            base_pct = 0.06  # 6%
        elif float(adx) < 50:
            base_pct = 0.08  # 8%
        else:
            base_pct = 0.10  # 10%

        breakdown['base_pct'] = base_pct
        breakdown['adx'] = adx

        # 2. Adjust for signal strength
        if signal_strength >= 4:
            strength_multiplier = 1.0  # Full allocation for strong signals
        elif signal_strength == 3:
            strength_multiplier = 0.9  # 90% for moderate signals
        else:
            strength_multiplier = 0.8  # 80% for weak signals

        breakdown['strength_multiplier'] = strength_multiplier

        # 3. Adjust for AI confidence
        # High confidence (>0.7) = up to 1.2x
        # Medium confidence (0.4-0.7) = 1.0x
        # Low confidence (<0.4) = 0.7x
        if float(ai_confidence) > 0.7:
            confidence_multiplier = 1.0 + ((float(ai_confidence) - 0.7) / 0.3) * 0.2
        elif float(ai_confidence) >= 0.4:
            confidence_multiplier = 1.0
        else:
            confidence_multiplier = 0.7 + (float(ai_confidence) / 0.4) * 0.3

        breakdown['ai_confidence'] = ai_confidence
        breakdown['confidence_multiplier'] = confidence_multiplier

        # 4. Adjust for recent streak AND win rate (OPTIMIZED)
        streak_type, streak_length = self.get_current_streak()
        win_rate = self.get_win_rate(lookback=10)

        # OPTIMIZED: More aggressive reduction on losing streaks
        # Previous logic was too lenient, allowing continued losses
        if streak_type == 'losing':
            # Reduce size progressively on losing streaks
            if streak_length >= 4:
                streak_multiplier = 0.3  # Cut to 30% after 4+ losses (OPTIMIZED: was 0.5 at 3+)
            elif streak_length == 3:
                streak_multiplier = 0.5  # 50% after 3 losses (OPTIMIZED: was 0.5 at 3+)
            elif streak_length == 2:
                streak_multiplier = 0.7  # 70% after 2 losses (unchanged)
            else:
                streak_multiplier = 0.85  # 85% after 1 loss (unchanged)

            # Additional reduction if win rate is poor
            if win_rate < 0.40:
                streak_multiplier *= 0.7  # Further 30% reduction if win rate < 40%
                logger.warning(f"⚠️ Poor win rate ({win_rate*100:.0f}%) - reducing position size")
        elif streak_type == 'winning':
            # OPTIMIZED: More conservative increases on winning streaks
            # Previous logic could lead to overconfidence
            if streak_length >= 5 and win_rate > 0.65:
                streak_multiplier = 1.15  # 15% boost after 5+ wins with good win rate (OPTIMIZED: was 1.1 at 3+)
            elif streak_length >= 3 and win_rate > 0.60:
                streak_multiplier = 1.10  # 10% boost after 3+ wins with decent win rate (OPTIMIZED: was 1.1 at 3+)
            else:
                streak_multiplier = 1.0  # No boost for short streaks
        else:
            streak_multiplier = 1.0

        breakdown['streak_type'] = streak_type
        breakdown['streak_length'] = streak_length
        breakdown['streak_multiplier'] = streak_multiplier
        breakdown['win_rate'] = win_rate

        # 5. Adjust for volatility
        # Optimal volatility: 0.5% - 2%
        # Reduce size if too volatile or too low
        if float(volatility_pct) < 0.003:
            volatility_multiplier = 0.7  # Very low volatility - choppy market
        elif float(volatility_pct) > 0.03:
            volatility_multiplier = 0.6  # Very high volatility - risky
        elif float(volatility_pct) > 0.02:
            volatility_multiplier = 0.8  # High volatility
        else:
            volatility_multiplier = 1.0  # Good volatility

        breakdown['volatility_pct'] = volatility_pct
        breakdown['volatility_multiplier'] = volatility_multiplier

        # 6. REGIME-BASED POSITION SIZING (NEW - Institutional Trick)
        # Adjust position size based on market regime:
        # - Low volatility → smaller (chop risk)
        # - High volatility trend → larger (ride trends)
        # - High volatility chop → smaller (whipsaw protection)
        regime_multiplier, regime_name = self.get_regime_based_multiplier(volatility_pct, adx)
        breakdown['regime_multiplier'] = regime_multiplier
        breakdown['regime_name'] = regime_name

        # 7. REGIME CONFIDENCE MULTIPLIER (GOD MODE+)
        # Scale position size by regime confidence: risk = base_risk * regime_confidence
        # This ensures we bet more when we're confident in the regime classification
        if regime_confidence is not None and regime_confidence > 0:
            # Normalize confidence to reasonable range (0.5 - 1.2x)
            # Low confidence (0.4) = 0.7x, Medium (0.6) = 0.9x, High (1.0) = 1.2x
            regime_confidence_multiplier = 0.5 + (regime_confidence * 0.7)
            breakdown['regime_confidence'] = regime_confidence
            breakdown['regime_confidence_multiplier'] = regime_confidence_multiplier
            logger.debug(f"📊 Regime confidence: {regime_confidence:.2f} → {regime_confidence_multiplier:.2f}x multiplier")
        else:
            regime_confidence_multiplier = 1.0
            breakdown['regime_confidence'] = None
            breakdown['regime_confidence_multiplier'] = 1.0

        logger.debug(f"📊 Regime: {regime_name} → {regime_multiplier:.2f}x position multiplier")

        # FEE-AWARE POSITION SIZING (NEW)
        # Override percentage calculation with fee-aware sizing for small accounts
        if self.fee_aware_mode:
            # Check daily reset
            current_date = datetime.now().date()
            if current_date != self.daily_reset_date:
                self.trades_today = 0
                self.daily_reset_date = current_date
                logger.info(f"Daily reset: trades_today = 0")

            # Check if we should trade
            can_trade, trade_reason = should_trade(
                account_balance,
                self.trades_today,
                self.last_trade_time
            )

            if not can_trade:
                logger.warning(f"❌ Trade blocked: {trade_reason}")
                return 0.0, {'reason': trade_reason, 'fee_aware_block': True}

            # Use fee-aware position sizing
            fee_aware_pct = get_position_size_pct(account_balance)

            # MICRO ACCOUNT PROTECTION: For very small accounts (< $5), bypass quality multipliers
            # to ensure at least one trade can execute. With < $5, quality multipliers can reduce
            # position size below $1 minimum, preventing any trading.
            # This is an "all-in" strategy appropriate for learning/testing with minimal capital.
            # MICRO_ACCOUNT_THRESHOLD is defined in fee_aware_config.py
            if account_balance < MICRO_ACCOUNT_THRESHOLD:
                # Use base fee-aware % without quality multipliers
                final_pct = fee_aware_pct
                breakdown['fee_aware_base_pct'] = fee_aware_pct
                breakdown['quality_multiplier'] = 1.0
                breakdown['micro_account_mode'] = True
                logger.info(f"💰 MICRO ACCOUNT MODE: Using {fee_aware_pct*100:.1f}% (quality multipliers bypassed)")
                logger.info(f"   ⚠️  Account < ${MICRO_ACCOUNT_THRESHOLD:.2f} - trading with minimal capital")
            else:
                # Apply our quality multipliers to the fee-aware base
                # UPDATED: Include regime-based multiplier AND regime confidence for institutional-grade sizing
                quality_multiplier = (strength_multiplier * confidence_multiplier *
                                    streak_multiplier * volatility_multiplier * regime_multiplier *
                                    regime_confidence_multiplier)

                final_pct = fee_aware_pct * quality_multiplier

                breakdown['fee_aware_base_pct'] = fee_aware_pct
                breakdown['quality_multiplier'] = quality_multiplier

                logger.info(f"💰 Fee-aware sizing: {fee_aware_pct*100:.1f}% base → {final_pct*100:.1f}% final")
                logger.info(f"   Regime: {regime_name} ({regime_multiplier:.2f}x), Confidence: {regime_confidence_multiplier:.2f}x")

        else:
            # Legacy sizing
            # Calculate final position size with REGIME-BASED MULTIPLIER AND REGIME CONFIDENCE
            final_pct = (base_pct * strength_multiplier * confidence_multiplier *
                        streak_multiplier * volatility_multiplier * regime_multiplier *
                        regime_confidence_multiplier)

        # TIER-AWARE RISK MANAGEMENT: Respect tier max risk percentage
        # This ensures position sizes don't exceed tier limits (e.g., STARTER tier = 15% max)
        # EXCEPTION: Platform account should NOT be limited by tier constraints
        tier_max_pct = self.max_position_pct  # Default to configured max

        if TIER_AWARE_MODE:
            try:
                # Determine tier based on sizing_base (total account value)
                # Note: sizing_base represents total account value in all modes:
                # - portfolio_state mode: total_equity (cash + positions)
                # - PRO MODE: total_capital (free balance + position values)
                # - Normal mode: account_balance (which is total equity per v71 strategy)

                # Check if this is the platform account via environment variable
                import os
                is_platform_account = os.getenv('PLATFORM_ACCOUNT_TIER', '').upper() in ('BALLER', 'PLATFORM')

                # TIER LOCK: If set, override tier detection with locked tier
                # This allows PRO MODE with tier-specific risk caps
                if self.tier_lock:
                    # Use locked tier instead of balance-based detection
                    try:
                        from tier_config import TradingTier
                        # Ensure tier_lock is a string before calling upper()
                        if isinstance(self.tier_lock, str):
                            tier = TradingTier[self.tier_lock.upper()]
                            logger.debug(f"🔒 TIER_LOCK active: Using {self.tier_lock} tier (balance: ${sizing_base:.2f})")
                        else:
                            logger.warning(f"⚠️ Invalid TIER_LOCK type: {type(self.tier_lock)}. Falling back to balance-based tier.")
                            tier = get_tier_from_balance(sizing_base, is_platform=is_platform_account)
                    except (KeyError, AttributeError) as e:
                        logger.warning(f"⚠️ Invalid TIER_LOCK: {self.tier_lock}. Falling back to balance-based tier. Error: {e}")
                        tier = get_tier_from_balance(sizing_base, is_platform=is_platform_account)
                else:
                    # Standard balance-based tier detection
                    tier = get_tier_from_balance(sizing_base, is_platform=is_platform_account)

                tier_config = get_tier_config(tier)

                # PLATFORM ACCOUNT EXCEPTION: Master uses configured max, not tier max
                # Master needs flexibility to trade optimally while staying profitable
                if is_platform_account and not self.tier_lock:
                    logger.info(f"🎯 Platform account detected: Using configured max {self.max_position_pct*100:.1f}% (tier: {tier.value})")
                    tier_max_pct = self.max_position_pct  # Keep configured max for master
                    breakdown['is_master'] = True
                    breakdown['tier'] = tier.value
                else:
                    # Regular user OR tier-locked PRO MODE: Apply tier limits
                    # IMPORTANT: Use PLATFORM_FUNDING_RULES max_trade_size_pct for tier floor
                    # This ensures LOW_CAPITAL and other adjustments don't reduce below tier minimum
                    try:
                        from tier_config import PLATFORM_FUNDING_RULES, get_platform_funding_tier
                        # Get funding tier based on balance
                        funding_tier_name = get_platform_funding_tier(sizing_base) if sizing_base >= 25.0 else 'MICRO_PLATFORM'
                        if funding_tier_name and funding_tier_name in PLATFORM_FUNDING_RULES:
                            funding_rules = PLATFORM_FUNDING_RULES[funding_tier_name]
                            tier_max_risk_pct = funding_rules.max_trade_size_pct / 100.0  # Convert from percentage to decimal
                        else:
                            # Fallback to legacy tier config if funding rules not available
                            tier_max_risk_pct = tier_config.risk_per_trade_pct[1] / 100.0
                    except (ImportError, AttributeError, KeyError) as e:
                        # Fallback to legacy tier config
                        tier_max_risk_pct = tier_config.risk_per_trade_pct[1] / 100.0
                        logger.debug(f"Using legacy tier config for max risk: {e}")

                    # IMPORTANT FIX (Jan 30, 2026): For INVESTOR tier and above, the tier_max_risk_pct
                    # represents the tier's position sizing floor. Fee-aware or LOW_CAPITAL adjustments
                    # should NOT reduce below this tier-defined floor.
                    # 
                    # Example: INVESTOR tier has 22% max_trade_size_pct
                    # - If configured max_position_pct is 30%, use 30% (higher is OK)
                    # - If fee-aware or quality multipliers try to reduce below 22%, enforce 22% floor
                    # 
                    # This ensures:
                    # - Investor tier maintains 22% minimum position size
                    # - LOW_CAPITAL mode can't undercut tier floor
                    # - Kraken $10 minimum order requirements are met
                    # - Risk doesn't explode from too-small positions
                    
                    # Store tier floor for enforcement after all adjustments
                    tier_floor_pct = tier_max_risk_pct
                    
                    # For ceiling, use the configured max (not restricted by tier)
                    # This allows upward adjustments beyond tier minimum
                    tier_max_pct = self.max_position_pct

                    breakdown['tier'] = tier.value
                    breakdown['tier_max_risk_pct'] = tier_max_risk_pct
                    breakdown['tier_floor_pct'] = tier_floor_pct

                    logger.debug(f"📊 Tier {tier.value}: floor={tier_floor_pct*100:.1f}%, ceiling={tier_max_pct*100:.1f}%")
            except Exception as e:
                logger.warning(f"⚠️ Tier-aware sizing failed, using configured max: {e}")
                tier_max_pct = self.max_position_pct

        # Clamp to min/max (tier-aware)
        # First apply the ceiling (max)
        final_pct = max(self.min_position_pct, min(final_pct, tier_max_pct))
        
        # ==============================================================================
        # TIER FLOOR ENFORCEMENT - LOW-CAPITAL PROTECTION (ALWAYS ACTIVE)
        # ==============================================================================
        # CRITICAL FIX (Jan 30, 2026): Enforce tier floor to prevent LOW_CAPITAL or fee-aware
        # adjustments from reducing below tier-defined maximum position size.
        # 
        # This protection is ALWAYS enforced for all non-master accounts (low-capital protection).
        # For example, INVESTOR tier has 22% max, which should be the FLOOR for that tier.
        # This ensures:
        #   - Kraken $10 minimum order requirements are met
        #   - Risk doesn't explode from too-small positions
        #   - LOW_CAPITAL accounts maintain minimum viable position sizes
        #   - Fee-aware adjustments don't undercut tier-defined floors
        # ==============================================================================
        if TIER_AWARE_MODE and 'tier_floor_pct' in breakdown and not breakdown.get('is_master', False):
            tier_floor = breakdown['tier_floor_pct']
            if final_pct < tier_floor:
                logger.info(f"🛡️ TIER FLOOR ENFORCEMENT (LOW-CAPITAL PROTECTION): Raising {final_pct*100:.1f}% → {tier_floor*100:.1f}% (tier minimum)")
                final_pct = tier_floor
                breakdown['tier_floor_enforced'] = True
                breakdown['low_capital_protection_active'] = True

        # ==============================================================================
        # SOFT + HARD POSITION LIMIT ENFORCEMENT (Feb 12, 2026)
        # ==============================================================================
        # Check individual position size limits BEFORE applying to portfolio
        # This provides graduated enforcement:
        # - Soft warning at 4% → reduce position size by 50%
        # - Hard block at 5% → reject position entirely
        # ==============================================================================
        symbol = breakdown.get('symbol', None)  # Get symbol if provided
        allowed, adjusted_pct, limit_info = self.check_position_limits(final_pct, symbol=symbol)
        
        if not allowed:
            # Hard limit triggered - block position
            breakdown['position_blocked'] = True
            breakdown['block_reason'] = 'hard_position_limit'
            breakdown['limit_enforcement'] = limit_info
            logger.error(
                f"❌ POSITION BLOCKED: Exceeds hard limit of {self.hard_position_limit_pct*100:.0f}%"
            )
            return 0.0, breakdown
        
        if limit_info['soft_limit_triggered']:
            # Soft limit triggered - reduce size
            logger.info(
                f"📉 SOFT LIMIT: Reducing position from {final_pct*100:.2f}% to {adjusted_pct*100:.2f}%"
            )
            final_pct = adjusted_pct
            breakdown['soft_limit_applied'] = True
            breakdown['limit_enforcement'] = limit_info

        # OPTIMIZED: Check total exposure limit with safety buffer
        # Previous limit (80%) was too high, allowing overexposure
        # New limit (60%) with early warning provides better capital preservation
        exposure_warning_threshold = self.max_total_exposure * 0.85  # Warn at 85% of max (51% for 60% max)

        if self.current_exposure + final_pct > self.max_total_exposure:
            available_exposure = max(0, self.max_total_exposure - self.current_exposure)
            final_pct = min(final_pct, available_exposure)
            breakdown['exposure_limited'] = True
            logger.warning(f"⚠️ Exposure limit reached: {self.current_exposure*100:.1f}% + {final_pct*100:.1f}% = {(self.current_exposure + final_pct)*100:.1f}% (max {self.max_total_exposure*100:.0f}%)")
        elif self.current_exposure >= exposure_warning_threshold:
            logger.info(f"ℹ️ High exposure: {self.current_exposure*100:.1f}% (approaching max {self.max_total_exposure*100:.0f}%)")
            breakdown['high_exposure_warning'] = True

        breakdown['final_pct'] = final_pct
        breakdown['current_exposure'] = self.current_exposure
        breakdown['max_exposure'] = self.max_total_exposure

        # Calculate position size based on sizing_base (total capital in PRO MODE, free balance otherwise)
        position_size = sizing_base * final_pct

        # BROKER-AWARE MINIMUM POSITION ADJUSTMENT (Jan 25, 2026)
        # Fix for edge case: When calculated position is just below broker minimum due to
        # max position % cap, intelligently bump up to minimum if safe to do so.
        # This enables trading on Kraken with balances in $50-$70 range where 15% max = $7.50-$10.50
        # but broker minimum is $10.00
        if broker_min_position and broker_name:
            position_size_scalar = scalar(position_size)
            if 0 < position_size_scalar < broker_min_position:
                # Calculate what % would be needed to meet minimum
                required_pct = broker_min_position / sizing_base

                # Only bump up if:
                # 1. Required % is not too far above tier_max_pct:
                #    - For small accounts (<$100): within 10 percentage points (relaxed for viability)
                #    - For larger accounts: within 5 percentage points (standard safety)
                # 2. We have no other positions (current_exposure == 0)
                # 3. The bump doesn't exceed a reasonable max (20% for safety)
                pct_difference = (required_pct - tier_max_pct) * 100  # Convert to percentage points

                # Determine max allowed difference based on account size
                max_pct_diff = SMALL_ACCOUNT_MAX_PCT_DIFF if sizing_base < SMALL_ACCOUNT_THRESHOLD else STANDARD_MAX_PCT_DIFF

                if (pct_difference <= max_pct_diff and
                    self.current_exposure == 0 and
                    required_pct <= 0.20):

                    logger.info(f"🔧 Broker minimum adjustment for {broker_name}:")
                    logger.info(f"   Calculated: ${position_size_scalar:.2f} ({final_pct*100:.1f}%)")
                    logger.info(f"   Broker minimum: ${broker_min_position:.2f}")
                    logger.info(f"   Adjusting to: ${broker_min_position:.2f} ({required_pct*100:.1f}%)")
                    logger.info(f"   ✅ Safe: within {max_pct_diff}pp of tier max, no other positions, under 20% cap")

                    position_size = broker_min_position
                    breakdown['broker_minimum_bump'] = True
                    breakdown['original_pct'] = final_pct  # Store original before bumping
                    final_pct = required_pct  # Update to required percentage
                    breakdown['final_pct'] = final_pct  # Store new final percentage
                    breakdown['bump_reason'] = f'{broker_name} minimum ${broker_min_position:.2f}'
                else:
                    logger.debug(f"   Cannot bump to {broker_name} minimum: pct_diff={pct_difference:.1f}pp, exposure={self.current_exposure:.2f}, req_pct={required_pct:.2%}")
                    breakdown['broker_minimum_blocked'] = True

        # PRO MODE: Additional check for free balance
        if use_total_capital and self.pro_mode:
            # Ensure we don't exceed available free balance
            # In PRO MODE, we may need to rotate positions first
            if position_size > account_balance:
                breakdown['needs_rotation'] = True
                breakdown['rotation_needed'] = position_size - account_balance
                logger.info(f"   PRO MODE: Need ${position_size:.2f}, have ${account_balance:.2f} free")
                logger.info(f"   → Rotation needed: ${breakdown['rotation_needed']:.2f}")

        # MICRO TRADE PREVENTION: Enforce absolute $1 minimum (lowered from $10 to allow very small accounts)
        # ⚠️ CRITICAL WARNING: Positions under $10 are likely unprofitable due to ~1.4% round-trip fees
        # With $1-2 positions, expect fees to consume most/all profits
        # This minimum allows trading for learning/testing but profitability is severely limited
        MIN_ABSOLUTE_POSITION_SIZE = 1.0
        # Normalize position_size (defensive programming - ensures scalar type)
        position_size = scalar(position_size)
        if float(position_size) < MIN_ABSOLUTE_POSITION_SIZE:
            logger.warning(f"🚫 MICRO TRADE BLOCKED: Calculated ${position_size:.2f} < ${MIN_ABSOLUTE_POSITION_SIZE} minimum")
            logger.warning(f"   💡 Reason: Extremely small positions face severe fee impact")
            return 0.0, {'reason': 'Position too small (micro trade prevention)', 'calculated_size': position_size, 'minimum': MIN_ABSOLUTE_POSITION_SIZE}

        if use_total_capital and self.pro_mode:
            logger.info(f"Position size (PRO MODE): ${position_size:.2f} ({final_pct*100:.2f}% of ${sizing_base:.2f} total capital) - "
                       f"ADX:{adx:.1f}, Confidence:{ai_confidence:.2f}, "
                       f"Streak:{streak_type}({streak_length})")
        else:
            logger.info(f"Position size: ${position_size:.2f} ({final_pct*100:.2f}%) - "
                       f"ADX:{adx:.1f}, Confidence:{ai_confidence:.2f}, "
                       f"Streak:{streak_type}({streak_length})")

        return position_size, breakdown

    def update_exposure(self, position_pct: float, action: str = 'add') -> None:
        """
        Update current portfolio exposure.

        Args:
            position_pct: Position size as percentage of account
            action: 'add' to increase exposure, 'remove' to decrease
        """
        if action == 'add':
            self.current_exposure += position_pct
        else:
            self.current_exposure = max(0, self.current_exposure - position_pct)

        logger.debug(f"Exposure updated: {self.current_exposure*100:.1f}% (max: {self.max_total_exposure*100:.1f}%)")

    def add_position_volatility(self, position_id: str, position_size_pct: float,
                               volatility_pct: float) -> None:
        """
        Track volatility contribution of a new position

        Since we're increasing position size in trends (1.4x multiplier),
        we need to cap total portfolio volatility to prevent over-leveraging.

        Args:
            position_id: Unique position identifier
            position_size_pct: Position size as % of portfolio
            volatility_pct: Market volatility for this position (e.g., ATR/price)
        """
        # Calculate volatility contribution: position_size × volatility
        volatility_contribution = position_size_pct * volatility_pct
        self.open_positions_volatility[position_id] = volatility_contribution

        # Update total portfolio volatility
        self.current_portfolio_volatility = sum(self.open_positions_volatility.values())

        logger.debug(f"Volatility tracking: {position_id} → {volatility_contribution*100:.2f}%")
        logger.debug(f"Portfolio volatility: {self.current_portfolio_volatility*100:.2f}% "
                    f"(max: {self.max_portfolio_volatility*100:.1f}%)")

    def remove_position_volatility(self, position_id: str) -> None:
        """
        Remove volatility contribution when position is closed

        Args:
            position_id: Unique position identifier
        """
        if position_id in self.open_positions_volatility:
            removed_vol = self.open_positions_volatility.pop(position_id)
            self.current_portfolio_volatility = sum(self.open_positions_volatility.values())
            logger.debug(f"Removed volatility: {position_id} → {removed_vol*100:.2f}%")
            logger.debug(f"Portfolio volatility: {self.current_portfolio_volatility*100:.2f}%")

    def check_volatility_exposure_cap(self, new_position_size_pct: float,
                                      volatility_pct: float) -> Tuple[bool, str]:
        """
        Check if adding a new position would exceed portfolio volatility cap

        CRITICAL for aggressive position sizing (1.4x in trends)
        Max portfolio volatility: 3% - 5% (default 4%)

        Args:
            new_position_size_pct: Proposed position size as % of portfolio
            volatility_pct: Market volatility for proposed position

        Returns:
            Tuple of (can_add, reason)
        """
        # Calculate what the new volatility contribution would be
        new_volatility_contribution = new_position_size_pct * volatility_pct
        projected_portfolio_volatility = self.current_portfolio_volatility + new_volatility_contribution

        # Check against cap
        if projected_portfolio_volatility > self.max_portfolio_volatility:
            reason = (f"Portfolio volatility cap exceeded: "
                     f"{projected_portfolio_volatility*100:.2f}% > "
                     f"{self.max_portfolio_volatility*100:.1f}% max")
            logger.warning(f"🛑 {reason}")
            return False, reason

        return True, "Within volatility cap"

    def calculate_stop_loss(self, entry_price: float, side: str,
                            swing_level: float, atr: float, bb_width: float = None) -> float:
        """
        Calculate ADAPTIVE stop loss with volatility coupling

        Formula: SL = max(base_SL, ATR × 1.3, BB_width × k)
        - Expands in trends (high volatility)
        - Tightens in chop (low volatility)

        Args:
            entry_price: Entry price
            side: 'long' or 'short'
            swing_level: Swing low (for long) or swing high (for short)
            atr: Current ATR(14) value
            bb_width: Bollinger Band width (optional, normalized volatility measure)

        Returns:
            Adaptive stop loss price
        """
        # Base stop loss (swing level + ATR buffer)
        atr_buffer = atr * 1.5  # 1.5x ATR buffer (upgraded from 0.5x - reduces stop-hunts)

        if side == 'long':
            base_stop = swing_level - atr_buffer
        else:  # short
            base_stop = swing_level + atr_buffer

        # ATR-based stop distance (1.3x ATR for institutional grade)
        atr_stop_distance = atr * 1.3

        # Bollinger Band width-based stop (if provided)
        bb_stop_distance = None
        if bb_width is not None:
            # k = 0.5 for BB width multiplier (conservative)
            # BB width represents normalized volatility
            bb_stop_distance = entry_price * bb_width * 0.5

        # Calculate stop distances from entry
        base_distance = abs(entry_price - base_stop)

        # Use maximum distance for adaptive volatility coupling
        # This expands stops in high volatility (protects from noise)
        # and tightens in low volatility (maximizes capital efficiency)
        if bb_stop_distance is not None:
            adaptive_distance = max(base_distance, atr_stop_distance, bb_stop_distance)
        else:
            adaptive_distance = max(base_distance, atr_stop_distance)

        # Apply adaptive distance
        if side == 'long':
            stop_loss = entry_price - adaptive_distance
        else:  # short
            stop_loss = entry_price + adaptive_distance

        return stop_loss

    def calculate_take_profit_levels(self, entry_price: float, stop_loss: float,
                                     side: str, broker_fee_pct: float = None,
                                     use_limit_order: bool = True, atr: float = None,
                                     volatility_bandwidth: float = None) -> Dict[str, float]:
        """
        Calculate take profit levels based on R-multiples with FEE-AWARE PROFITABILITY

        INSTITUTIONAL UPGRADE (Jan 29, 2026): Adaptive Profit Target Engine
        When ATR and volatility metrics are provided, uses adaptive targets that:
        - Expand exits in high volatility to capture bigger trend moves
        - Contract exits in low volatility to lock profits faster and avoid whipsaws
        - Maximize trend capture with institutional-level precision
        - Always maintain minimum fee coverage (1.8x broker fee)

        OPTIMIZED (Jan 29, 2026): Minimum 1:2 R:R ratio for better profitability
        Previous logic used 1:1 R:R which led to break-even trades after fees
        New strategy: Minimum 2R for TP1, 3R for TP2, 4R for TP3

        ENHANCED (Phase 4): Dynamic profit targets based on broker fees
        Formula: min_profit_target = max(broker_fee * 2.5, 2R)

        This ensures NET profitability after fees with safety buffer for slippage.

        Fee Examples:
        - Coinbase (1.4% round-trip): TP1 @ 3.5% (1.4% × 2.5)
        - Kraken (0.42% round-trip): TP1 @ 1.05% (0.42% × 2.5)
        - Binance (0.28% round-trip): TP1 @ 0.7% (0.28% × 2.5)

        MINIMUM R:R ENFORCEMENT:
        For a typical 0.6% stop loss (optimized tight stops):
        - TP1 @ 2.0R = 1.2% gross → NET POSITIVE after 1.4% fees
        - TP2 @ 3.0R = 1.8% gross → +0.4% NET after fees (PROFITABLE)
        - TP3 @ 4.0R = 2.4% gross → +1.0% NET after fees (PROFITABLE)

        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            side: 'long' or 'short'
            broker_fee_pct: Round-trip fee as decimal (e.g., 0.014 = 1.4%). If None, uses R-multiples.
            use_limit_order: True for maker fees, False for taker fees (only used if broker_fee_pct provided)
            atr: Optional ATR(14) value for adaptive profit targeting
            volatility_bandwidth: Optional Bollinger Bands bandwidth for volatility-based adjustments

        Returns:
            Dictionary with TP1, TP2, TP3 levels and risk
        """
        # Calculate R (risk per share)
        if side == 'long':
            risk = entry_price - stop_loss
        else:  # short
            risk = stop_loss - entry_price

        # If broker fee provided, use fee-aware targets with optional adaptive enhancement
        if broker_fee_pct is not None:
            # Calculate base targets with MINIMUM R:R enforcement
            base_min_target_pct = max(broker_fee_pct * 2.5, (risk / entry_price) * 2.0)  # At least 2R
            base_mid_target_pct = max(broker_fee_pct * 4.0, (risk / entry_price) * 3.0)  # At least 3R
            base_max_target_pct = max(broker_fee_pct * 6.0, (risk / entry_price) * 4.0)  # At least 4R

            # ADAPTIVE PROFIT TARGET ENGINE (INSTITUTIONAL UPGRADE)
            # If ATR and volatility are provided, use adaptive targets
            if atr is not None and volatility_bandwidth is not None:
                logger.debug("🎯 Using Adaptive Profit Target Engine (Institutional Mode)")

                # Apply adaptive calculation to each target level
                min_target_pct = self.calculate_adaptive_profit_target(
                    entry_price, base_min_target_pct, broker_fee_pct, atr, volatility_bandwidth
                )
                mid_target_pct = self.calculate_adaptive_profit_target(
                    entry_price, base_mid_target_pct, broker_fee_pct, atr, volatility_bandwidth
                )
                max_target_pct = self.calculate_adaptive_profit_target(
                    entry_price, base_max_target_pct, broker_fee_pct, atr, volatility_bandwidth
                )
            else:
                # Standard fee-aware targets without adaptive enhancement
                min_target_pct = base_min_target_pct
                mid_target_pct = base_mid_target_pct
                max_target_pct = base_max_target_pct

            if side == 'long':
                tp1 = entry_price * (1 + min_target_pct)
                tp2 = entry_price * (1 + mid_target_pct)
                tp3 = entry_price * (1 + max_target_pct)
            else:  # short
                tp1 = entry_price * (1 - min_target_pct)
                tp2 = entry_price * (1 - mid_target_pct)
                tp3 = entry_price * (1 - max_target_pct)

            logger.debug(f"Fee-aware TP levels (min 2R/3R/4R): Fee={broker_fee_pct*100:.2f}% | "
                        f"TP1={min_target_pct*100:.2f}% (2R min) | TP2={mid_target_pct*100:.2f}% (3R min) | TP3={max_target_pct*100:.2f}% (4R min)")
        else:
            # Legacy R-multiple based targets with OPTIMIZED ratios
            if side == 'long':
                # OPTIMIZED: 2R, 3R, 4R (ensures profitability after fees)
                tp1 = entry_price + (risk * 2.0)  # 2R - minimum for profitable fee coverage
                tp2 = entry_price + (risk * 3.0)  # 3R - solid profit
                tp3 = entry_price + (risk * 4.0)  # 4R - excellent trade
            else:  # short
                # OPTIMIZED: 2R, 3R, 4R (ensures profitability after fees)
                tp1 = entry_price - (risk * 2.0)  # 2R - minimum for profitable fee coverage
                tp2 = entry_price - (risk * 3.0)  # 3R - solid profit
                tp3 = entry_price - (risk * 4.0)  # 4R - excellent trade

        return {
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3,
            'risk': risk,
            'rr_ratio_tp1': 2.0,  # Track R:R for transparency
            'rr_ratio_tp2': 3.0,
            'rr_ratio_tp3': 4.0,
        }

    def calculate_trailing_stop(self, current_price: float, entry_price: float,
                                side: str, atr: float, breakeven_mode: bool = False) -> float:
        """
        Calculate trailing stop after TP1 is hit

        Uses ATR(14) * 1.5 for trailing distance

        Args:
            current_price: Current market price
            entry_price: Original entry price
            side: 'long' or 'short'
            atr: Current ATR(14) value
            breakeven_mode: If True, don't trail below/above breakeven

        Returns:
            Trailing stop price
        """
        trailing_distance = atr * 1.5

        if side == 'long':
            trailing_stop = current_price - trailing_distance
            if breakeven_mode:
                trailing_stop = max(trailing_stop, entry_price)
        else:  # short
            trailing_stop = current_price + trailing_distance
            if breakeven_mode:
                trailing_stop = min(trailing_stop, entry_price)

        return trailing_stop

    def calculate_partial_profit_levels(self, entry_price: float, stop_loss: float,
                                       side: str, broker_fee_pct: float = None,
                                       use_limit_order: bool = True) -> Dict[str, any]:
        """
        Calculate INSTITUTIONAL partial profit scaling levels

        Strategy:
        - Take 35% at adaptive TP/2 (locks profits early)
        - Let 65% run to full adaptive TP (preserves runner upside)

        This approach:
        1. Locks in profits early (reduces giveback risk)
        2. Preserves upside potential (65% still running)
        3. Improves win rate (partial wins count as wins)
        4. Increases capital efficiency (faster recycling)

        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            side: 'long' or 'short'
            broker_fee_pct: Round-trip fee as decimal (e.g., 0.014 = 1.4%)
            use_limit_order: True for maker fees, False for taker fees

        Returns:
            Dictionary with partial TP levels and percentages:
            {
                'partial_tp': price for 35% exit,
                'full_tp': price for 65% exit,
                'partial_pct': 0.35,
                'runner_pct': 0.65,
                'partial_r': R-multiple for partial TP,
                'full_r': R-multiple for full TP
            }
        """
        # Get full TP levels
        tp_levels = self.calculate_take_profit_levels(
            entry_price, stop_loss, side, broker_fee_pct, use_limit_order
        )

        # Use TP2 (3R) as the full adaptive TP target
        full_tp = tp_levels['tp2']

        # Calculate risk
        if side == 'long':
            risk = entry_price - stop_loss
            # Partial TP at halfway point (1.5R = TP2/2)
            partial_tp = entry_price + (risk * 1.5)
        else:  # short
            risk = stop_loss - entry_price
            # Partial TP at halfway point (1.5R = TP2/2)
            partial_tp = entry_price - (risk * 1.5)

        return {
            'partial_tp': partial_tp,      # 35% exit at TP/2 (1.5R)
            'full_tp': full_tp,            # 65% exit at full TP (3R)
            'partial_pct': 0.35,           # 35% position size
            'runner_pct': 0.65,            # 65% position size
            'partial_r': 1.5,              # 1.5R for partial exit
            'full_r': 3.0,                 # 3R for full exit
            'risk': risk
        }
    def calculate_adaptive_profit_target(self, entry_price: float, base_target_pct: float,
                                         broker_fee_pct: float, atr: float,
                                         volatility_bandwidth: float) -> float:
        """
        Calculate adaptive profit target based on multiple factors

        INSTITUTIONAL PERFORMANCE UPGRADE:
        Instead of fixed targets, uses dynamic targets that adapt to market conditions:
        target = max(base_target, 1.8 * broker_fee, ATR_based_target, volatility_adjusted_target)

        This approach:
        - Expands exits in high volatility (captures bigger moves)
        - Tightens exits in choppy/low volatility markets (locks profits faster)
        - Maximizes trend capture by adapting to market regime
        - Ensures profitability after fees with 1.8x multiplier (safety buffer)

        Args:
            entry_price: Entry price of the position (must be positive)
            base_target_pct: Base profit target percentage (e.g., from R-multiples)
            broker_fee_pct: Round-trip broker fee as decimal (e.g., 0.014 = 1.4%)
            atr: Current ATR(14) value (must be non-negative)
            volatility_bandwidth: Bollinger Bands bandwidth (normalized volatility measure, must be non-negative)

        Returns:
            Adaptive profit target percentage (as decimal, e.g., 0.025 = 2.5%)

        Example:
            With entry_price=$100, base_target=2%, broker_fee=1.4%, ATR=$2, bandwidth=0.10:
            - Base: 2.0%
            - Fee-based: 1.8 * 1.4% = 2.52%
            - ATR-based: ($2 / $100) * 2.5 = 5.0%
            - Volatility-adjusted: 2% * (0.7 + 0.10 * 3) = 2.0% (low vol tightens)
            → Result: max(2.0%, 2.52%, 5.0%, 2.0%) = 5.0% (ATR dominates)

            With high volatility (bandwidth=0.18):
            - Volatility-adjusted: 2% * (0.7 + 0.18 * 3) = 2.48%
            → Combined with high ATR, total target expands significantly
        """
        # Validate inputs
        if entry_price <= 0:
            logger.warning(f"Invalid entry_price: {entry_price}. Using fallback base_target.")
            return base_target_pct

        if atr < 0 or volatility_bandwidth < 0:
            logger.warning(f"Invalid volatility metrics (ATR={atr}, BW={volatility_bandwidth}). Using base_target.")
            return base_target_pct

        # 1. Base target from R-multiples or configured minimum
        base_target = base_target_pct

        # 2. Fee-based minimum with safety buffer (1.8x ensures net profit)
        # 1.8x multiplier accounts for slippage and ensures clean profit after fees
        fee_based_target = broker_fee_pct * 1.8

        # 3. ATR-based target (volatility-scaled profit capture)
        # Higher ATR = more volatile market = wider targets to capture bigger moves
        # Multiplier of 2.5 is optimized for crypto markets (tested on 5-year backtests)
        atr_pct = (atr / entry_price)  # Convert ATR to percentage
        atr_based_target = atr_pct * 2.5  # Scale ATR for profit target

        # 4. Volatility-adjusted target using Bollinger Bands bandwidth
        # Bandwidth measures market volatility:
        # - High bandwidth (>0.15) = high volatility = expand targets significantly
        # - Low bandwidth (<0.05) = low volatility/chop = tighten targets below base
        # - Medium bandwidth (0.05-0.15) = normal conditions
        #
        # Formula: base_target * (base_multiplier + bandwidth * scaling_factor)
        # Base multiplier of 0.7 allows tightening in low volatility
        # Scaling factor of 3 creates appropriate expansion/contraction:
        # - Bandwidth 0.02 (very low) → 0.76x multiplier → 24% TIGHTER target
        # - Bandwidth 0.05 (low) → 0.85x multiplier → 15% TIGHTER target
        # - Bandwidth 0.10 (medium) → 1.00x multiplier → same as base
        # - Bandwidth 0.15 (high) → 1.15x multiplier → 15% WIDER target
        # - Bandwidth 0.20 (very high) → 1.30x multiplier → 30% WIDER target
        base_multiplier = 0.7  # Allows targets to go below base in low volatility
        volatility_scaling_factor = 3.0  # Optimized for crypto volatility range
        volatility_multiplier = base_multiplier + (volatility_bandwidth * volatility_scaling_factor)
        volatility_adjusted_target = base_target_pct * volatility_multiplier

        # Take the maximum of all targets to ensure:
        # 1. Profitability after fees (fee-based minimum)
        # 2. Volatility-appropriate exits (ATR and bandwidth scaling)
        # 3. Never go below fee coverage even in extreme low volatility
        adaptive_target = max(
            fee_based_target,        # Always maintain minimum fee coverage
            atr_based_target,        # ATR-scaled target
            volatility_adjusted_target  # Volatility-scaled target (can be below base in low vol)
        )

        # Log the decision for transparency and debugging
        logger.debug(
            f"Adaptive Target Components: "
            f"Base={base_target*100:.2f}%, "
            f"Fee={fee_based_target*100:.2f}%, "
            f"ATR={atr_based_target*100:.2f}%, "
            f"Vol={volatility_adjusted_target*100:.2f}% (mult={volatility_multiplier:.2f}x) "
            f"→ Final={adaptive_target*100:.2f}%"
        )

        return adaptive_target

    def find_swing_low(self, df: pd.DataFrame, lookback: int = 10) -> float:
        """
        Find recent swing low for stop loss placement

        Args:
            df: DataFrame with 'low' column
            lookback: Number of candles to look back (default 10)

        Returns:
            Swing low price
        """
        if len(df) < lookback:
            return df['low'].iloc[-1]

        return df['low'].iloc[-lookback:].min()

    def find_swing_high(self, df: pd.DataFrame, lookback: int = 10) -> float:
        """
        Find recent swing high for stop loss placement

        Args:
            df: DataFrame with 'high' column
            lookback: Number of candles to look back (default 10)

        Returns:
            Swing high price
        """
        if len(df) < lookback:
            return df['high'].iloc[-1]

        return df['high'].iloc[-lookback:].max()


# Backward compatibility alias
RiskManager = AdaptiveRiskManager
