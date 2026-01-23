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
    from tier_config import get_tier_from_balance, get_tier_config
    TIER_AWARE_MODE = True
    logger.info("✅ Tier configuration loaded - TIER-AWARE RISK MANAGEMENT ACTIVE")
except ImportError:
    TIER_AWARE_MODE = False
    logger.warning("⚠️ Tier config not found - tier enforcement disabled")


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
    
    def __init__(self, min_position_pct=0.02, max_position_pct=0.15,
                 max_total_exposure=0.80, use_exchange_profiles=False,
                 pro_mode=False, min_free_reserve_pct=0.15, tier_lock=None):
        """
        Initialize Adaptive Risk Manager - OPTIMAL PROFITABILITY MODE v7.4
        Updated Jan 23, 2026: Added tier_lock parameter for PRO MODE + tier enforcement
        
        Args:
            min_position_pct: Minimum position size as % of account (default 2% - conservative for weak trends)
            max_position_pct: Maximum position size as % of account (default 15% - reduced for better risk control)
            max_total_exposure: Maximum total exposure across all positions (default 80% - allows multiple positions)
            use_exchange_profiles: If True, uses exchange-specific risk profiles (default False)
            pro_mode: If True, enables PRO MODE with position rotation (default False)
            min_free_reserve_pct: Minimum free balance % to maintain in PRO MODE (default 15%)
            tier_lock: If set, locks risk to specific tier limits (e.g., 'SAVER', 'INVESTOR')
        """
        self.min_position_pct = min_position_pct
        self.max_position_pct = max_position_pct
        self.max_total_exposure = max_total_exposure
        self.pro_mode = pro_mode
        self.min_free_reserve_pct = min_free_reserve_pct
        self.tier_lock = tier_lock  # NEW: Tier locking for PRO MODE
        
        # Track recent trades for streak analysis
        self.recent_trades: List[Dict] = []
        self.max_trade_history = 20  # Keep last 20 trades
        
        # Current exposure tracking
        self.current_exposure = 0.0
        
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
        
        logger.debug(f"Trade recorded: {outcome}, PnL: ${pnl:.2f}")
    
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
            
            if outcome == 'breakeven':
                break  # Breakeven ends streak
            
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
    
    def calculate_position_size(self, account_balance: float, adx: float, 
                               signal_strength: int = 3, ai_confidence: float = 0.5,
                               volatility_pct: float = 0.01, 
                               use_total_capital: bool = False,
                               position_value: float = 0.0,
                               portfolio_state=None) -> Tuple[float, Dict]:
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
        
        Returns:
            Tuple of (position_size, breakdown_dict)
            - position_size: Position size in USD
            - breakdown_dict: Details of sizing calculations
        """
        breakdown = {}
        
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
        
        # 4. Adjust for recent streak
        streak_type, streak_length = self.get_current_streak()
        
        if streak_type == 'losing':
            # Reduce size progressively on losing streaks
            if streak_length >= 3:
                streak_multiplier = 0.5  # Cut to 50% after 3+ losses
            elif streak_length == 2:
                streak_multiplier = 0.7  # 70% after 2 losses
            else:
                streak_multiplier = 0.85  # 85% after 1 loss
        elif streak_type == 'winning':
            # Cautiously increase on winning streaks (but cap it)
            if streak_length >= 3:
                streak_multiplier = 1.1  # Small boost after 3+ wins
            else:
                streak_multiplier = 1.0
        else:
            streak_multiplier = 1.0
        
        breakdown['streak_type'] = streak_type
        breakdown['streak_length'] = streak_length
        breakdown['streak_multiplier'] = streak_multiplier
        
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
                quality_multiplier = (strength_multiplier * confidence_multiplier * 
                                    streak_multiplier * volatility_multiplier)
                
                final_pct = fee_aware_pct * quality_multiplier
                
                breakdown['fee_aware_base_pct'] = fee_aware_pct
                breakdown['quality_multiplier'] = quality_multiplier
                
                logger.info(f"💰 Fee-aware sizing: {fee_aware_pct*100:.1f}% base → {final_pct*100:.1f}% final")
        
        else:
            # Legacy sizing
            # Calculate final position size
            final_pct = (base_pct * strength_multiplier * confidence_multiplier * 
                        streak_multiplier * volatility_multiplier)
        
        # TIER-AWARE RISK MANAGEMENT: Respect tier max risk percentage
        # This ensures position sizes don't exceed tier limits (e.g., STARTER tier = 15% max)
        # EXCEPTION: Master account should NOT be limited by tier constraints
        tier_max_pct = self.max_position_pct  # Default to configured max
        
        if TIER_AWARE_MODE:
            try:
                # Determine tier based on sizing_base (total account value)
                # Note: sizing_base represents total account value in all modes:
                # - portfolio_state mode: total_equity (cash + positions)
                # - PRO MODE: total_capital (free balance + position values)
                # - Normal mode: account_balance (which is total equity per v71 strategy)
                
                # Check if this is the master account via environment variable
                import os
                is_master_account = os.getenv('MASTER_ACCOUNT_TIER', '').upper() in ('BALLER', 'MASTER')
                
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
                            tier = get_tier_from_balance(sizing_base, is_master=is_master_account)
                    except (KeyError, AttributeError) as e:
                        logger.warning(f"⚠️ Invalid TIER_LOCK: {self.tier_lock}. Falling back to balance-based tier. Error: {e}")
                        tier = get_tier_from_balance(sizing_base, is_master=is_master_account)
                else:
                    # Standard balance-based tier detection
                    tier = get_tier_from_balance(sizing_base, is_master=is_master_account)
                
                tier_config = get_tier_config(tier)
                
                # MASTER ACCOUNT EXCEPTION: Master uses configured max, not tier max
                # Master needs flexibility to trade optimally while staying profitable
                if is_master_account and not self.tier_lock:
                    logger.info(f"🎯 Master account detected: Using configured max {self.max_position_pct*100:.1f}% (tier: {tier.value})")
                    tier_max_pct = self.max_position_pct  # Keep configured max for master
                    breakdown['is_master'] = True
                    breakdown['tier'] = tier.value
                else:
                    # Regular user OR tier-locked PRO MODE: Apply tier limits
                    # Get tier's max risk percentage (second element of risk_per_trade_pct tuple)
                    tier_max_risk_pct = tier_config.risk_per_trade_pct[1] / 100.0  # Convert from percentage to decimal
                    
                    # Use the more restrictive of tier max or configured max
                    tier_max_pct = min(self.max_position_pct, tier_max_risk_pct)
                    
                    breakdown['tier'] = tier.value
                    breakdown['tier_max_risk_pct'] = tier_max_risk_pct
                    
                    if self.tier_lock:
                        logger.debug(f"🔒 TIER_LOCK: {tier.value} tier restricts to {tier_max_risk_pct*100:.1f}%")
                    elif tier_max_risk_pct < self.max_position_pct:
                        logger.debug(f"📊 Tier-aware limit: {tier.value} tier restricts to {tier_max_risk_pct*100:.1f}% (configured max: {self.max_position_pct*100:.1f}%)")
            except Exception as e:
                logger.warning(f"⚠️ Tier-aware sizing failed, using configured max: {e}")
                tier_max_pct = self.max_position_pct
        
        # Clamp to min/max (tier-aware)
        final_pct = max(self.min_position_pct, min(final_pct, tier_max_pct))
        
        # Check total exposure limit
        if self.current_exposure + final_pct > self.max_total_exposure:
            available_exposure = max(0, self.max_total_exposure - self.current_exposure)
            final_pct = min(final_pct, available_exposure)
            breakdown['exposure_limited'] = True
        
        breakdown['final_pct'] = final_pct
        breakdown['current_exposure'] = self.current_exposure
        
        # Calculate position size based on sizing_base (total capital in PRO MODE, free balance otherwise)
        position_size = sizing_base * final_pct
        
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
    
    def calculate_stop_loss(self, entry_price: float, side: str, 
                            swing_level: float, atr: float) -> float:
        """
        Calculate stop loss based on swing low/high plus ATR buffer
        
        Args:
            entry_price: Entry price
            side: 'long' or 'short'
            swing_level: Swing low (for long) or swing high (for short)
            atr: Current ATR(14) value
        
        Returns:
            Stop loss price
        """
        atr_buffer = atr * 1.5  # 1.5x ATR buffer (upgraded from 0.5x - reduces stop-hunts)
        
        if side == 'long':
            # Stop below swing low with ATR buffer
            stop_loss = swing_level - atr_buffer
        else:  # short
            # Stop above swing high with ATR buffer
            stop_loss = swing_level + atr_buffer
        
        return stop_loss
    
    def calculate_take_profit_levels(self, entry_price: float, stop_loss: float,
                                     side: str) -> Dict[str, float]:
        """
        Calculate take profit levels based on R-multiples
        
        FEE-AWARE PROFITABILITY FIX (Dec 27, 2025):
        Adjusted to ensure NET profitability after Coinbase fees (~1.4% round-trip)
        
        Previous targets (0.5R, 1R, 1.5R) were too low and resulted in NET LOSSES
        after fees. Updated targets ensure minimum ~0.6% NET profit:
        
        - TP1: 1.0R (ensures >1.4% gross to beat fees)
        - TP2: 1.5R (provides cushion for volatility)
        - TP3: 2.0R (meaningful profit target)
        
        For a typical 2% stop loss:
        - TP1 @ 2% gross → ~0.6% NET after fees (PROFITABLE)
        - TP2 @ 3% gross → ~1.6% NET after fees (PROFITABLE)
        - TP3 @ 4% gross → ~2.6% NET after fees (PROFITABLE)
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            side: 'long' or 'short'
        
        Returns:
            Dictionary with TP1 (1.0R), TP2 (1.5R), TP3 (2.0R) levels
        """
        # Calculate R (risk per share)
        if side == 'long':
            risk = entry_price - stop_loss
            # Fee-aware targets: 1R, 1.5R, 2R (ensures profitability after fees)
            tp1 = entry_price + (risk * 1.0)  # 1R - minimum for fee coverage
            tp2 = entry_price + (risk * 1.5)  # 1.5R - solid profit
            tp3 = entry_price + (risk * 2.0)  # 2R - excellent trade
        else:  # short
            risk = stop_loss - entry_price
            # Fee-aware targets: 1R, 1.5R, 2R (ensures profitability after fees)
            tp1 = entry_price - (risk * 1.0)  # 1R - minimum for fee coverage
            tp2 = entry_price - (risk * 1.5)  # 1.5R - solid profit
            tp3 = entry_price - (risk * 2.0)  # 2R - excellent trade
        
        return {
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3,
            'risk': risk
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

