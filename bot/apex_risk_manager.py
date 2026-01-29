"""
NIJA Apex Strategy v7.1 - Risk Manager
========================================

Handles position sizing, risk calculations, and trend quality assessment.
"""

import pandas as pd
from typing import Dict, Tuple
from apex_config import POSITION_SIZING, RISK_LIMITS, STOP_LOSS
from indicators import scalar


class ApexRiskManager:
    """
    Risk management and position sizing for Apex Strategy v7.1
    """

    def __init__(self, account_balance: float):
        """
        Initialize risk manager

        Args:
            account_balance: Current account balance in USD
        """
        self.account_balance = account_balance
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.open_positions = []

    def update_account_balance(self, new_balance: float):
        """Update account balance"""
        self.account_balance = new_balance

    def assess_trend_quality(self, adx: float, plus_di: float, minus_di: float) -> str:
        """
        Assess trend quality based on ADX

        Args:
            adx: ADX value
            plus_di: +DI value
            minus_di: -DI value

        Returns:
            str: 'weak', 'good', 'strong', or 'very_strong'
        """
        adx = scalar(adx)
        if adx >= 40:
            return 'very_strong'
        elif adx >= 30:
            return 'strong'
        elif adx >= 25:
            return 'good'
        elif adx >= 20:
            return 'weak'
        else:
            return 'no_trend'

    def get_trend_direction(self, plus_di: float, minus_di: float) -> str:
        """
        Get trend direction from DI values

        Args:
            plus_di: +DI value
            minus_di: -DI value

        Returns:
            str: 'UP', 'DOWN', or 'NEUTRAL'
        """
        if plus_di > minus_di:
            return 'UP'
        elif minus_di > plus_di:
            return 'DOWN'
        else:
            return 'NEUTRAL'

    def calculate_position_size(
        self,
        trend_quality: str,
        entry_price: float,
        stop_loss_price: float
    ) -> Tuple[float, float, float]:
        """
        Calculate position size based on trend quality and risk

        Args:
            trend_quality: Trend quality ('weak', 'good', 'strong', 'very_strong')
            entry_price: Entry price for the trade
            stop_loss_price: Stop loss price

        Returns:
            tuple: (position_size_usd, position_size_pct, risk_amount)
        """
        # Get position size percentage based on trend quality
        sizing_config = POSITION_SIZING['trend_quality']

        if trend_quality in sizing_config:
            position_size_pct = sizing_config[trend_quality]['position_size']
        else:
            # Default to minimum if trend quality is unknown
            position_size_pct = POSITION_SIZING['min_position_size']

        # Enforce min/max limits
        position_size_pct = max(
            POSITION_SIZING['min_position_size'],
            min(position_size_pct, POSITION_SIZING['max_position_size'])
        )

        # Calculate position size in USD
        position_size_usd = self.account_balance * position_size_pct

        # Calculate risk amount (distance from entry to stop)
        risk_per_unit = abs(entry_price - stop_loss_price)
        risk_amount = (risk_per_unit / entry_price) * position_size_usd

        return position_size_usd, position_size_pct, risk_amount

    def calculate_r_multiple(self, entry_price: float, current_price: float, stop_loss_price: float) -> float:
        """
        Calculate R-multiple (profit in terms of initial risk)

        Args:
            entry_price: Entry price
            current_price: Current price
            stop_loss_price: Stop loss price

        Returns:
            float: R-multiple
        """
        initial_risk = abs(entry_price - stop_loss_price)

        if initial_risk == 0:
            return 0.0

        current_profit = current_price - entry_price
        r_multiple = current_profit / initial_risk

        return r_multiple

    def calculate_take_profit_levels(
        self,
        entry_price: float,
        stop_loss_price: float,
        side: str = 'long'
    ) -> Dict[str, float]:
        """
        Calculate take profit levels based on R-multiples

        Args:
            entry_price: Entry price
            stop_loss_price: Stop loss price
            side: 'long' or 'short'

        Returns:
            dict: Take profit levels {'TP1': price, 'TP2': price, 'TP3': price}
        """
        initial_risk = abs(entry_price - stop_loss_price)

        if side == 'long':
            tp1 = entry_price + (initial_risk * 1.0)  # 1R
            tp2 = entry_price + (initial_risk * 2.0)  # 2R
            tp3 = entry_price + (initial_risk * 3.0)  # 3R
        else:  # short
            tp1 = entry_price - (initial_risk * 1.0)  # 1R
            tp2 = entry_price - (initial_risk * 2.0)  # 2R
            tp3 = entry_price - (initial_risk * 3.0)  # 3R

        return {
            'TP1': tp1,
            'TP2': tp2,
            'TP3': tp3,
        }

    def check_risk_limits(self) -> Dict[str, bool]:
        """
        Check if risk limits are being respected

        Returns:
            dict: Status of various risk checks
        """
        # Calculate current exposure
        total_exposure = sum(pos.get('size_usd', 0) for pos in self.open_positions)
        exposure_pct = total_exposure / self.account_balance if self.account_balance > 0 else 0

        # Daily loss check
        daily_loss_pct = abs(self.daily_pnl / self.account_balance) if self.account_balance > 0 else 0

        return {
            'max_exposure_ok': exposure_pct <= RISK_LIMITS['max_exposure'],
            'daily_loss_ok': daily_loss_pct <= RISK_LIMITS['max_daily_loss'] or self.daily_pnl >= 0,
            'max_positions_ok': len(self.open_positions) < RISK_LIMITS['max_positions'],
            'max_trades_ok': self.daily_trades < RISK_LIMITS['max_trades_per_day'],
            'current_exposure_pct': exposure_pct,
            'daily_loss_pct': daily_loss_pct,
        }

    def can_open_position(self) -> Tuple[bool, str]:
        """
        Check if we can open a new position based on risk limits

        Returns:
            tuple: (can_open, reason)
        """
        risk_status = self.check_risk_limits()

        if not risk_status['max_exposure_ok']:
            return False, f"Max exposure reached ({risk_status['current_exposure_pct']:.1%})"

        if not risk_status['daily_loss_ok']:
            return False, f"Daily loss limit reached ({risk_status['daily_loss_pct']:.1%})"

        if not risk_status['max_positions_ok']:
            return False, f"Maximum positions ({RISK_LIMITS['max_positions']}) reached"

        if not risk_status['max_trades_ok']:
            return False, f"Daily trade limit ({RISK_LIMITS['max_trades_per_day']}) reached"

        return True, "All risk checks passed"

    def add_position(self, position: Dict):
        """Add a new position to tracking"""
        self.open_positions.append(position)
        self.daily_trades += 1

    def remove_position(self, position_id: str):
        """Remove a position from tracking"""
        self.open_positions = [p for p in self.open_positions if p.get('id') != position_id]

    def update_daily_pnl(self, pnl: float):
        """Update daily P&L"""
        self.daily_pnl += pnl

    def reset_daily_stats(self):
        """Reset daily statistics (call at start of new trading day)"""
        self.daily_pnl = 0.0
        self.daily_trades = 0

    def get_position_summary(self) -> Dict:
        """
        Get summary of current positions

        Returns:
            dict: Position summary statistics
        """
        if not self.open_positions:
            return {
                'total_positions': 0,
                'total_exposure_usd': 0,
                'total_exposure_pct': 0,
                'average_position_size': 0,
            }

        total_exposure = sum(pos.get('size_usd', 0) for pos in self.open_positions)

        return {
            'total_positions': len(self.open_positions),
            'total_exposure_usd': total_exposure,
            'total_exposure_pct': total_exposure / self.account_balance if self.account_balance > 0 else 0,
            'average_position_size': total_exposure / len(self.open_positions),
            'daily_pnl': self.daily_pnl,
            'daily_trades': self.daily_trades,
        }
