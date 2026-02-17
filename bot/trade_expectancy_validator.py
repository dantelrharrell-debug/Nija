"""
NIJA Trade Expectancy Validator
================================

Layer 2: Trade Expectancy Improvement

Validates trade quality before entry based on:
1. Minimum R-multiple (reward-to-risk ratio)
2. Volatility-adjusted stop placement
3. First-move confirmation (volume/range expansion)

Philosophy: Stop accepting technically valid but mathematically stupid trades.
"""

import logging
from typing import Dict, Tuple, Optional
from datetime import datetime
import pandas as pd
import numpy as np

logger = logging.getLogger("nija.trade_expectancy")

# Import scalar helper for indicator conversions
try:
    from indicators import scalar
except ImportError:
    def scalar(x):
        """Convert indicator value to float, handling tuples/lists"""
        if isinstance(x, (tuple, list)):
            if len(x) == 0:
                raise ValueError("Cannot convert empty tuple/list to scalar")
            return float(x[0])
        return float(x)


class TradeExpectancyValidator:
    """
    Validates trade expectancy before entry
    
    Critical Gates:
    1. R-Multiple ≥ 1.5 (preferably 2.0)
    2. Stop placement outside noise (ATR-based)
    3. First-move confirmation (volume/range expansion)
    
    These filters remove mathematically stupid trades that:
    - Have poor risk/reward
    - Have stops in noise
    - Enter before market confirms direction
    """
    
    # R-Multiple thresholds
    MIN_R_MULTIPLE_STRICT = 2.0      # Ideal: 2:1 reward-to-risk
    MIN_R_MULTIPLE_ACCEPTABLE = 1.5  # Minimum acceptable: 1.5:1
    
    # Stop placement (volatility-adjusted)
    ATR_STOP_MULTIPLIER = 1.2        # Stop = ATR × 1.2 (outside noise)
    MIN_STOP_DISTANCE_PCT = 0.005    # Minimum 0.5% stop distance
    MAX_STOP_DISTANCE_PCT = 0.030    # Maximum 3% stop distance
    
    # First-move confirmation thresholds
    VOLUME_EXPANSION_MIN = 1.3       # Current volume ≥ 1.3x avg
    RANGE_EXPANSION_MIN = 1.2        # Current range ≥ 1.2x avg
    BREAKOUT_HOLD_BARS = 1           # Must hold above level for 1 bar
    
    def __init__(self, strict_mode: bool = False):
        """
        Initialize Trade Expectancy Validator
        
        Args:
            strict_mode: If True, use stricter R-multiple (2.0), else 1.5
        """
        self.strict_mode = strict_mode
        self.min_r_multiple = self.MIN_R_MULTIPLE_STRICT if strict_mode else self.MIN_R_MULTIPLE_ACCEPTABLE
        
        # Track real expectancy over 100 trades
        self.completed_trades = []  # Store trade results
        self.MIN_TRADES_FOR_PROJECTIONS = 100  # Need 100 trades before ROI projections
        
        logger.info(f"✅ Trade Expectancy Validator initialized (R-multiple ≥ {self.min_r_multiple})")
        logger.info(f"   ROI projections will be available after {self.MIN_TRADES_FOR_PROJECTIONS} trades")
    
    def calculate_r_multiple(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float
    ) -> float:
        """
        Calculate R-multiple (reward-to-risk ratio)
        
        Args:
            entry_price: Proposed entry price
            stop_loss: Stop loss price
            take_profit: Take profit price (can be first TP level)
        
        Returns:
            R-multiple (reward / risk)
        """
        if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
            return 0.0
        
        # Calculate risk (entry to stop)
        risk = abs(entry_price - stop_loss)
        
        # Calculate reward (entry to target)
        reward = abs(take_profit - entry_price)
        
        if risk == 0:
            return 0.0
        
        r_multiple = reward / risk
        return r_multiple
    
    def validate_r_multiple(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float
    ) -> Tuple[bool, str, float]:
        """
        Validate that trade has acceptable R-multiple
        
        Args:
            entry_price: Proposed entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
        
        Returns:
            Tuple of (valid, reason, r_multiple)
        """
        r_multiple = self.calculate_r_multiple(entry_price, stop_loss, take_profit)
        
        if r_multiple >= self.min_r_multiple:
            return True, f"Good R-multiple: {r_multiple:.2f}R", r_multiple
        else:
            return False, f"Poor R-multiple: {r_multiple:.2f}R < {self.min_r_multiple}R minimum", r_multiple
    
    def calculate_volatility_adjusted_stop(
        self,
        df: pd.DataFrame,
        entry_price: float,
        side: str,
        structure_stop: Optional[float] = None
    ) -> Tuple[float, str]:
        """
        Calculate volatility-adjusted stop loss
        
        Stop = max(ATR × 1.2, structure-based level)
        
        Args:
            df: Price DataFrame with 'atr' column
            entry_price: Entry price
            side: 'long' or 'short'
            structure_stop: Optional structure-based stop (swing low/high)
        
        Returns:
            Tuple of (stop_price, reason)
        """
        if 'atr' not in df.columns or len(df) == 0:
            # Fallback: use percentage-based stop
            stop_pct = self.MIN_STOP_DISTANCE_PCT
            if side == 'long':
                stop_price = entry_price * (1 - stop_pct)
            else:
                stop_price = entry_price * (1 + stop_pct)
            return stop_price, f"Fallback {stop_pct*100:.1f}% stop (no ATR)"
        
        # Get ATR
        atr = scalar(df['atr'].iloc[-1])
        
        # Calculate ATR-based stop distance
        atr_stop_distance = atr * self.ATR_STOP_MULTIPLIER
        
        # Convert to percentage
        atr_stop_pct = atr_stop_distance / entry_price
        
        # Clamp to reasonable range
        stop_pct = max(self.MIN_STOP_DISTANCE_PCT, min(atr_stop_pct, self.MAX_STOP_DISTANCE_PCT))
        
        # Calculate ATR-based stop price
        if side == 'long':
            atr_stop = entry_price * (1 - stop_pct)
        else:
            atr_stop = entry_price * (1 + stop_pct)
        
        # If structure stop provided, use the wider one (more conservative)
        if structure_stop is not None:
            if side == 'long':
                # For longs, use lower stop (more room)
                final_stop = min(atr_stop, structure_stop)
                if final_stop == structure_stop:
                    reason = f"Structure stop (ATR={atr_stop:.4f}, Structure={structure_stop:.4f})"
                else:
                    reason = f"ATR stop ({stop_pct*100:.2f}% = ATR×{self.ATR_STOP_MULTIPLIER})"
            else:
                # For shorts, use higher stop (more room)
                final_stop = max(atr_stop, structure_stop)
                if final_stop == structure_stop:
                    reason = f"Structure stop (ATR={atr_stop:.4f}, Structure={structure_stop:.4f})"
                else:
                    reason = f"ATR stop ({stop_pct*100:.2f}% = ATR×{self.ATR_STOP_MULTIPLIER})"
        else:
            final_stop = atr_stop
            reason = f"ATR stop ({stop_pct*100:.2f}% = ATR×{self.ATR_STOP_MULTIPLIER})"
        
        return final_stop, reason
    
    def validate_stop_placement(
        self,
        df: pd.DataFrame,
        entry_price: float,
        stop_loss: float,
        side: str
    ) -> Tuple[bool, str]:
        """
        Validate that stop is outside market noise
        
        Args:
            df: Price DataFrame with 'atr' column
            entry_price: Entry price
            stop_loss: Proposed stop loss
            side: 'long' or 'short'
        
        Returns:
            Tuple of (valid, reason)
        """
        if 'atr' not in df.columns or len(df) == 0:
            # Can't validate without ATR
            return True, "No ATR available (skipping stop validation)"
        
        # Get ATR
        atr = scalar(df['atr'].iloc[-1])
        
        # Calculate actual stop distance
        stop_distance = abs(entry_price - stop_loss)
        
        # Minimum stop distance should be ATR × 1.0 (inside noise)
        # Our stops should be ATR × 1.2 or more (outside noise)
        min_acceptable_distance = atr * 1.0  # Absolute minimum
        recommended_distance = atr * self.ATR_STOP_MULTIPLIER
        
        if stop_distance < min_acceptable_distance:
            return False, f"Stop too tight: {stop_distance:.4f} < ATR×1.0 ({min_acceptable_distance:.4f}) - inside noise"
        elif stop_distance < recommended_distance:
            return True, f"Stop acceptable but tight: {stop_distance:.4f} < ATR×{self.ATR_STOP_MULTIPLIER} ({recommended_distance:.4f})"
        else:
            return True, f"Stop well-placed: {stop_distance:.4f} ≥ ATR×{self.ATR_STOP_MULTIPLIER} ({recommended_distance:.4f})"
    
    def check_volume_expansion(self, df: pd.DataFrame, lookback: int = 20) -> Tuple[bool, str, float]:
        """
        Check if current volume shows expansion vs recent average
        
        Args:
            df: Price DataFrame with 'volume' column
            lookback: Bars to compare against
        
        Returns:
            Tuple of (is_expanding, reason, volume_ratio)
        """
        if 'volume' not in df.columns or len(df) < lookback + 1:
            return False, "Insufficient data for volume check", 0.0
        
        # Current bar volume
        current_volume = df['volume'].iloc[-1]
        
        # Average volume (excluding current bar)
        avg_volume = df['volume'].iloc[-lookback-1:-1].mean()
        
        if avg_volume == 0:
            return False, "Zero average volume", 0.0
        
        volume_ratio = current_volume / avg_volume
        
        if volume_ratio >= self.VOLUME_EXPANSION_MIN:
            return True, f"Volume expanding: {volume_ratio:.2f}x average", volume_ratio
        else:
            return False, f"Volume below expansion threshold: {volume_ratio:.2f}x < {self.VOLUME_EXPANSION_MIN}x", volume_ratio
    
    def check_range_expansion(self, df: pd.DataFrame, lookback: int = 20) -> Tuple[bool, str, float]:
        """
        Check if current candle range shows expansion vs recent average
        
        Args:
            df: Price DataFrame with 'high', 'low' columns
            lookback: Bars to compare against
        
        Returns:
            Tuple of (is_expanding, reason, range_ratio)
        """
        if 'high' not in df.columns or 'low' not in df.columns or len(df) < lookback + 1:
            return False, "Insufficient data for range check", 0.0
        
        # Current bar range
        current_range = df['high'].iloc[-1] - df['low'].iloc[-1]
        
        # Average range (excluding current bar)
        ranges = df['high'].iloc[-lookback-1:-1] - df['low'].iloc[-lookback-1:-1]
        avg_range = ranges.mean()
        
        if avg_range == 0:
            return False, "Zero average range", 0.0
        
        range_ratio = current_range / avg_range
        
        if range_ratio >= self.RANGE_EXPANSION_MIN:
            return True, f"Range expanding: {range_ratio:.2f}x average", range_ratio
        else:
            return False, f"Range below expansion threshold: {range_ratio:.2f}x < {self.RANGE_EXPANSION_MIN}x", range_ratio
    
    def check_first_move_confirmation(self, df: pd.DataFrame) -> Tuple[bool, str]:
        """
        Check for first-move confirmation (ONE of these must be true):
        - Volume expansion vs last 20 bars
        - Range expansion candle
        
        Args:
            df: Price DataFrame
        
        Returns:
            Tuple of (confirmed, reason)
        """
        confirmations = []
        
        # Check volume expansion
        volume_ok, volume_reason, volume_ratio = self.check_volume_expansion(df)
        if volume_ok:
            confirmations.append(f"Volume expansion ({volume_ratio:.2f}x)")
        
        # Check range expansion
        range_ok, range_reason, range_ratio = self.check_range_expansion(df)
        if range_ok:
            confirmations.append(f"Range expansion ({range_ratio:.2f}x)")
        
        if confirmations:
            return True, " + ".join(confirmations)
        else:
            return False, "No expansion confirmation (volume or range)"
    
    def validate_trade(
        self,
        df: pd.DataFrame,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        side: str,
        require_confirmation: bool = True
    ) -> Dict:
        """
        Complete trade validation
        
        Args:
            df: Price DataFrame
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            side: 'long' or 'short'
            require_confirmation: If True, require first-move confirmation
        
        Returns:
            Dict with validation results
        """
        result = {
            'valid': False,
            'reasons_passed': [],
            'reasons_failed': [],
            'r_multiple': 0.0,
            'stop_loss': stop_loss,
            'take_profit': take_profit
        }
        
        # 1. Check R-multiple
        r_valid, r_reason, r_multiple = self.validate_r_multiple(entry_price, stop_loss, take_profit)
        result['r_multiple'] = r_multiple
        
        if r_valid:
            result['reasons_passed'].append(f"✅ {r_reason}")
        else:
            result['reasons_failed'].append(f"❌ {r_reason}")
        
        # 2. Check stop placement
        stop_valid, stop_reason = self.validate_stop_placement(df, entry_price, stop_loss, side)
        
        if stop_valid:
            result['reasons_passed'].append(f"✅ {stop_reason}")
        else:
            result['reasons_failed'].append(f"❌ {stop_reason}")
        
        # 3. Check first-move confirmation (if required)
        if require_confirmation:
            confirmation_ok, confirmation_reason = self.check_first_move_confirmation(df)
            
            if confirmation_ok:
                result['reasons_passed'].append(f"✅ First-move: {confirmation_reason}")
            else:
                result['reasons_failed'].append(f"❌ First-move: {confirmation_reason}")
        else:
            result['reasons_passed'].append("⏭️ First-move confirmation skipped")
            confirmation_ok = True  # Don't block if not required
        
        # Trade is valid only if ALL checks pass
        result['valid'] = r_valid and stop_valid and confirmation_ok
        
        return result
    
    def record_completed_trade(self, win: bool, profit_pct: float, risk_pct: float) -> None:
        """
        Record a completed trade for expectancy calculation.
        
        Args:
            win: True if trade was profitable, False if loss
            profit_pct: Profit/loss percentage (e.g., 0.025 for 2.5%)
            risk_pct: Risk percentage (e.g., 0.006 for 0.6%)
        """
        trade = {
            'win': win,
            'profit_pct': profit_pct,
            'risk_pct': risk_pct,
            'r_multiple': profit_pct / risk_pct if risk_pct != 0 else 0,
            'timestamp': datetime.now()
        }
        
        self.completed_trades.append(trade)
        
        # Keep only last 100 trades for rolling calculation
        if len(self.completed_trades) > self.MIN_TRADES_FOR_PROJECTIONS:
            self.completed_trades = self.completed_trades[-self.MIN_TRADES_FOR_PROJECTIONS:]
        
        # Log progress
        if len(self.completed_trades) == self.MIN_TRADES_FOR_PROJECTIONS:
            logger.info(f"✅ Reached {self.MIN_TRADES_FOR_PROJECTIONS} trades - ROI projections now available!")
    
    def get_real_expectancy(self) -> Dict:
        """
        Calculate real expectancy from actual trades.
        
        Returns:
            Dict with expectancy metrics or warning if insufficient data
        """
        if len(self.completed_trades) < self.MIN_TRADES_FOR_PROJECTIONS:
            return {
                'sufficient_data': False,
                'trades_completed': len(self.completed_trades),
                'trades_needed': self.MIN_TRADES_FOR_PROJECTIONS - len(self.completed_trades),
                'warning': f"Need {self.MIN_TRADES_FOR_PROJECTIONS - len(self.completed_trades)} more trades before ROI projections"
            }
        
        # Calculate from last 100 trades
        trades = self.completed_trades[-self.MIN_TRADES_FOR_PROJECTIONS:]
        wins = [t for t in trades if t['win']]
        losses = [t for t in trades if not t['win']]
        
        win_rate = len(wins) / len(trades)
        
        avg_win = np.mean([t['profit_pct'] for t in wins]) if wins else 0
        avg_loss = abs(np.mean([t['profit_pct'] for t in losses])) if losses else 0
        
        # Expectancy = (Win% × Avg Win) - (Loss% × Avg Loss)
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        
        # Average R-multiple
        avg_r = np.mean([t['r_multiple'] for t in trades])
        
        return {
            'sufficient_data': True,
            'trades_completed': len(trades),
            'win_rate': win_rate,
            'avg_win_pct': avg_win,
            'avg_loss_pct': avg_loss,
            'expectancy_pct': expectancy,
            'avg_r_multiple': avg_r,
            'total_wins': len(wins),
            'total_losses': len(losses)
        }
    
    def should_show_roi_projections(self) -> bool:
        """
        Check if enough trades completed to show ROI projections.
        
        Returns:
            True if ≥100 trades completed, False otherwise
        """
        return len(self.completed_trades) >= self.MIN_TRADES_FOR_PROJECTIONS
    
    def get_roi_projection_warning(self) -> str:
        """
        Get warning message if ROI projections shown with insufficient data.
        
        Returns:
            Warning message or empty string if sufficient data
        """
        if self.should_show_roi_projections():
            return ""
        
        trades_needed = self.MIN_TRADES_FOR_PROJECTIONS - len(self.completed_trades)
        return (
            f"⚠️ WARNING: ROI projections require {self.MIN_TRADES_FOR_PROJECTIONS} trades. "
            f"Only {len(self.completed_trades)} completed. Need {trades_needed} more trades for accurate projections."
        )
