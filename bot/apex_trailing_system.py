"""
NIJA Apex Strategy v7.1 - Trailing Stop System
================================================

Advanced trailing stop system with:
- Break-even stop after TP1
- ATR-based trailing stops
- Multi-stage take profit management
"""

import pandas as pd
from typing import Dict, Optional
from apex_config import TRAILING_STOP, TAKE_PROFIT


class ApexTrailingSystem:
    """
    Trailing stop system for Apex Strategy v7.1
    """

    def __init__(self):
        """Initialize trailing system"""
        self.positions = {}

    def calculate_breakeven_stop(
        self,
        entry_price: float,
        side: str,
        buffer_pct: float = 0.001
    ) -> float:
        """
        Calculate break-even stop with small buffer

        Args:
            entry_price: Entry price
            side: 'long' or 'short'
            buffer_pct: Small buffer above/below entry (0.1% default)

        Returns:
            float: Break-even stop price
        """
        if side == 'long':
            return entry_price * (1 + buffer_pct)
        else:  # short
            return entry_price * (1 - buffer_pct)

    def calculate_atr_trailing_stop(
        self,
        current_price: float,
        atr: float,
        side: str,
        atr_multiplier: Optional[float] = None
    ) -> float:
        """
        Calculate ATR-based trailing stop

        Args:
            current_price: Current market price
            atr: ATR value
            side: 'long' or 'short'
            atr_multiplier: ATR multiplier (default from config)

        Returns:
            float: Trailing stop price
        """
        if atr_multiplier is None:
            atr_multiplier = TRAILING_STOP['atr_multiplier']

        trail_distance = atr * atr_multiplier

        if side == 'long':
            return current_price - trail_distance
        else:  # short
            return current_price + trail_distance

    def update_trailing_stop(
        self,
        position_id: str,
        current_price: float,
        entry_price: float,
        stop_loss_price: float,
        atr: float,
        side: str,
        r_multiple: float
    ) -> Dict:
        """
        Update trailing stop based on current profit level

        Args:
            position_id: Unique position identifier
            current_price: Current market price
            entry_price: Entry price
            stop_loss_price: Current stop loss
            atr: Current ATR value
            side: 'long' or 'short'
            r_multiple: Current R-multiple (profit in terms of initial risk)

        Returns:
            dict: Updated stop information
        """
        # Initialize position tracking if not exists
        if position_id not in self.positions:
            self.positions[position_id] = {
                'highest_r': 0,
                'tp1_hit': False,
                'tp2_hit': False,
                'tp3_hit': False,
                'breakeven_activated': False,
                'trailing_activated': False,
            }

        position_state = self.positions[position_id]
        new_stop = stop_loss_price
        action_taken = None

        # Track highest R achieved
        if r_multiple > position_state['highest_r']:
            position_state['highest_r'] = r_multiple

        # Check TP levels and activate appropriate stops
        activation_r = TRAILING_STOP['activation_r']

        if r_multiple >= activation_r and not position_state['breakeven_activated']:
            # Move to break-even after TP1
            new_stop = self.calculate_breakeven_stop(entry_price, side)
            position_state['breakeven_activated'] = True
            position_state['tp1_hit'] = True
            position_state['trailing_activated'] = True
            action_taken = 'breakeven_activated'

        elif position_state['trailing_activated']:
            # Calculate ATR trailing stop
            atr_stop = self.calculate_atr_trailing_stop(current_price, atr, side)

            # Only tighten stop, never widen
            if TRAILING_STOP['never_widen']:
                if side == 'long':
                    new_stop = max(stop_loss_price, atr_stop)
                else:  # short
                    new_stop = min(stop_loss_price, atr_stop)
            else:
                new_stop = atr_stop

            if new_stop != stop_loss_price:
                action_taken = 'trailing_stop_updated'

        # Check TP2 and TP3
        if r_multiple >= 2.0:
            position_state['tp2_hit'] = True
        if r_multiple >= 3.0:
            position_state['tp3_hit'] = True

        return {
            'new_stop': new_stop,
            'action_taken': action_taken,
            'position_state': position_state,
            'r_multiple': r_multiple,
        }

    def get_exit_signals(
        self,
        position_id: str,
        r_multiple: float,
        current_price: float,
        stop_loss_price: float,
        side: str
    ) -> Dict:
        """
        Get exit signals based on TP levels and stops

        Args:
            position_id: Unique position identifier
            r_multiple: Current R-multiple
            current_price: Current price
            stop_loss_price: Current stop loss
            side: 'long' or 'short'

        Returns:
            dict: Exit signals and percentages
        """
        if position_id not in self.positions:
            return {'should_exit': False, 'exit_percentage': 0, 'reason': None}

        position_state = self.positions[position_id]

        # Check stop loss hit
        stop_hit = False
        if side == 'long' and current_price <= stop_loss_price:
            stop_hit = True
        elif side == 'short' and current_price >= stop_loss_price:
            stop_hit = True

        if stop_hit:
            return {
                'should_exit': True,
                'exit_percentage': 1.0,  # Exit 100%
                'reason': 'stop_loss_hit',
            }

        # Check TP stages
        stages = TAKE_PROFIT['stages']

        for stage in stages:
            stage_r = stage['profit_r']
            exit_pct = stage['exit_percentage']
            stage_name = stage['name']
            tp_key = f"{stage_name.lower()}_hit"
            exit_key = f"{stage_name.lower()}_exited"

            # Initialize exit tracking
            if exit_key not in position_state:
                position_state[exit_key] = False

            # Check if we hit this TP level and haven't exited yet
            if r_multiple >= stage_r and not position_state.get(exit_key, False):
                position_state[tp_key] = True
                position_state[exit_key] = True

                return {
                    'should_exit': True,
                    'exit_percentage': exit_pct,
                    'reason': f'{stage_name}_reached',
                    'stage': stage_name,
                }

        return {'should_exit': False, 'exit_percentage': 0, 'reason': None}

    def check_trend_break(
        self,
        df: pd.DataFrame,
        side: str
    ) -> bool:
        """
        Check if trend has broken (EMA9 crosses EMA21)

        Args:
            df: DataFrame with price data
            side: 'long' or 'short'

        Returns:
            bool: True if trend broken
        """
        if len(df) < 21:
            return False

        # Calculate EMAs
        ema9 = df['close'].ewm(span=9, adjust=False).mean()
        ema21 = df['close'].ewm(span=21, adjust=False).mean()

        # Check current and previous values
        current_ema9 = ema9.iloc[-1]
        current_ema21 = ema21.iloc[-1]
        prev_ema9 = ema9.iloc[-2]
        prev_ema21 = ema21.iloc[-2]

        if side == 'long':
            # Trend breaks when EMA9 crosses below EMA21
            was_above = prev_ema9 > prev_ema21
            now_below = current_ema9 < current_ema21
            return was_above and now_below
        else:  # short
            # Trend breaks when EMA9 crosses above EMA21
            was_below = prev_ema9 < prev_ema21
            now_above = current_ema9 > current_ema21
            return was_below and now_above

    def remove_position(self, position_id: str):
        """Remove position from tracking"""
        if position_id in self.positions:
            del self.positions[position_id]

    def get_position_state(self, position_id: str) -> Optional[Dict]:
        """Get current state of a position"""
        return self.positions.get(position_id)

    def get_all_positions_summary(self) -> Dict:
        """Get summary of all tracked positions"""
        return {
            'total_positions': len(self.positions),
            'positions': {
                pid: {
                    'highest_r': state['highest_r'],
                    'tp1_hit': state.get('tp1_hit', False),
                    'tp2_hit': state.get('tp2_hit', False),
                    'tp3_hit': state.get('tp3_hit', False),
                    'breakeven_activated': state.get('breakeven_activated', False),
                    'trailing_activated': state.get('trailing_activated', False),
                }
                for pid, state in self.positions.items()
            }
        }
