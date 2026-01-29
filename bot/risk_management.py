"""
NIJA Apex Strategy v7.1 - Risk Management Module

Multi-stage dynamic risk management system:
- ADX-weighted position sizing
- ATR-based stop-loss calculation
- Tiered take-profit system (TP1, TP2, TP3)
- Trailing stop activation post-TP1
- Max drawdown tracking and limits
- Risk exposure management
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


class RiskManager:
    """
    Advanced risk management for NIJA Apex Strategy v7.1.
    """

    def __init__(self, account_balance, max_risk_per_trade=0.02,
                 max_daily_loss=0.025, max_total_exposure=0.30,
                 max_drawdown=0.10):
        """
        Initialize risk manager.

        Args:
            account_balance: Current account balance in USD
            max_risk_per_trade: Maximum risk per trade as decimal (default: 2%)
            max_daily_loss: Maximum daily loss as decimal (default: 2.5%)
            max_total_exposure: Maximum total exposure as decimal (default: 30%)
            max_drawdown: Maximum account drawdown as decimal (default: 10%)
        """
        self.account_balance = account_balance
        self.starting_balance = account_balance
        self.max_risk_per_trade = max_risk_per_trade
        self.max_daily_loss = max_daily_loss
        self.max_total_exposure = max_total_exposure
        self.max_drawdown = max_drawdown

        # Track daily performance
        self.daily_pnl = 0
        self.daily_reset_date = datetime.utcnow().date()

        # Track open positions
        self.open_positions = []  # List of position dicts
        self.total_exposure = 0

        # Drawdown tracking
        self.peak_balance = account_balance
        self.current_drawdown = 0

    def update_balance(self, new_balance):
        """Update account balance and recalculate drawdown."""
        self.account_balance = new_balance

        # Update peak balance
        if new_balance > self.peak_balance:
            self.peak_balance = new_balance

        # Calculate current drawdown
        if self.peak_balance > 0:
            self.current_drawdown = (self.peak_balance - new_balance) / self.peak_balance
        else:
            self.current_drawdown = 0

        # Reset daily PnL if new day
        today = datetime.utcnow().date()
        if today != self.daily_reset_date:
            self.daily_pnl = 0
            self.daily_reset_date = today

    def calculate_position_size_adx_weighted(self, signal_strength, adx_value,
                                             base_size_pct=0.03, max_size_pct=0.10):
        """
        Calculate position size with ADX weighting.

        Strong trends (high ADX) get larger positions.
        Weak trends (low ADX) get smaller positions.

        Args:
            signal_strength: Signal quality score (0-5)
            adx_value: Current ADX value
            base_size_pct: Base position size percentage (default: 3%)
            max_size_pct: Maximum position size percentage (default: 10%)

        Returns:
            dict: {
                'position_size_usd': float,
                'position_size_pct': float,
                'adx_multiplier': float,
                'signal_multiplier': float
            }
        """
        # ADX multiplier (0.5x to 1.5x based on ADX)
        # ADX < 20: 0.5x (weak trend)
        # ADX 20-40: 0.5x to 1.0x (moderate trend)
        # ADX > 40: 1.0x to 1.5x (strong trend)
        if adx_value < 20:
            adx_multiplier = 0.5
        elif adx_value < 40:
            adx_multiplier = 0.5 + (adx_value - 20) * 0.025  # Linear scale 0.5 to 1.0
        else:
            adx_multiplier = 1.0 + min((adx_value - 40) * 0.0125, 0.5)  # Linear scale 1.0 to 1.5

        # Signal strength multiplier (0.4x to 1.2x based on signal score)
        # Score 1-2: 0.4x to 0.6x
        # Score 3: 0.8x
        # Score 4: 1.0x
        # Score 5: 1.2x
        signal_multipliers = {
            1: 0.4,
            2: 0.6,
            3: 0.8,
            4: 1.0,
            5: 1.2
        }
        signal_multiplier = signal_multipliers.get(signal_strength, 0.6)

        # Calculate final position size
        position_size_pct = base_size_pct * adx_multiplier * signal_multiplier
        position_size_pct = min(position_size_pct, max_size_pct)
        position_size_pct = max(position_size_pct, 0.01)  # Minimum 1%

        position_size_usd = self.account_balance * position_size_pct

        return {
            'position_size_usd': position_size_usd,
            'position_size_pct': position_size_pct,
            'adx_multiplier': adx_multiplier,
            'signal_multiplier': signal_multiplier
        }

    def calculate_stop_loss_atr(self, entry_price, atr_value, direction='long',
                                atr_multiplier=1.5, min_stop_pct=0.003):
        """
        Calculate stop-loss with ATR buffer.

        Args:
            entry_price: Entry price
            atr_value: Current ATR value
            direction: 'long' or 'short'
            atr_multiplier: ATR multiplier for stop distance (default: 1.5)
            min_stop_pct: Minimum stop-loss percentage (default: 0.3%)

        Returns:
            dict: {
                'stop_price': float,
                'stop_distance': float,
                'stop_distance_pct': float
            }
        """
        # Calculate ATR-based stop distance
        atr_distance = atr_value * atr_multiplier

        # Ensure minimum stop distance
        min_stop_distance = entry_price * min_stop_pct
        stop_distance = max(atr_distance, min_stop_distance)

        # Calculate stop price
        if direction.lower() == 'long':
            stop_price = entry_price - stop_distance
        else:  # short
            stop_price = entry_price + stop_distance

        stop_distance_pct = stop_distance / entry_price if entry_price > 0 else 0

        return {
            'stop_price': stop_price,
            'stop_distance': stop_distance,
            'stop_distance_pct': stop_distance_pct
        }

    def calculate_tiered_take_profits(self, entry_price, direction='long',
                                     tp1_pct=0.008, tp2_pct=0.015, tp3_pct=0.025):
        """
        Calculate tiered take-profit levels.

        TP1: +0.8% (exit 50% of position, activate trailing stop)
        TP2: +1.5% (exit 30% of position)
        TP3: +2.5% (exit remaining 20%, runner continues with trail)

        Args:
            entry_price: Entry price
            direction: 'long' or 'short'
            tp1_pct: TP1 percentage (default: 0.8%)
            tp2_pct: TP2 percentage (default: 1.5%)
            tp3_pct: TP3 percentage (default: 2.5%)

        Returns:
            dict: {
                'tp1': {'price': float, 'pct': float, 'exit_size': 0.50},
                'tp2': {'price': float, 'pct': float, 'exit_size': 0.30},
                'tp3': {'price': float, 'pct': float, 'exit_size': 0.20}
            }
        """
        if direction.lower() == 'long':
            tp1_price = entry_price * (1 + tp1_pct)
            tp2_price = entry_price * (1 + tp2_pct)
            tp3_price = entry_price * (1 + tp3_pct)
        else:  # short
            tp1_price = entry_price * (1 - tp1_pct)
            tp2_price = entry_price * (1 - tp2_pct)
            tp3_price = entry_price * (1 - tp3_pct)

        return {
            'tp1': {
                'price': tp1_price,
                'pct': tp1_pct,
                'exit_size': 0.50,
                'description': 'First partial exit, activate trailing stop'
            },
            'tp2': {
                'price': tp2_price,
                'pct': tp2_pct,
                'exit_size': 0.30,
                'description': 'Second partial exit'
            },
            'tp3': {
                'price': tp3_price,
                'pct': tp3_pct,
                'exit_size': 0.20,
                'description': 'Final exit or continue trailing'
            }
        }

    def calculate_trailing_stop(self, entry_price, current_price, highest_price,
                               direction='long', trail_pct=0.005, min_trail_pct=0.003):
        """
        Calculate trailing stop price.

        Trailing stop activates after TP1 and trails price at specified distance.

        Args:
            entry_price: Original entry price
            current_price: Current market price
            highest_price: Highest price since entry (for long) or lowest (for short)
            direction: 'long' or 'short'
            trail_pct: Trailing distance percentage (default: 0.5%)
            min_trail_pct: Minimum trailing distance (default: 0.3%)

        Returns:
            dict: {
                'trail_price': float,
                'trail_distance': float,
                'trail_distance_pct': float,
                'locked_profit_pct': float
            }
        """
        if direction.lower() == 'long':
            # Trail below highest price
            trail_distance = highest_price * max(trail_pct, min_trail_pct)
            trail_price = highest_price - trail_distance

            # Calculate locked profit
            locked_profit_pct = (trail_price - entry_price) / entry_price if entry_price > 0 else 0
        else:  # short
            # Trail above lowest price
            trail_distance = highest_price * max(trail_pct, min_trail_pct)
            trail_price = highest_price + trail_distance

            # Calculate locked profit
            locked_profit_pct = (entry_price - trail_price) / entry_price if entry_price > 0 else 0

        return {
            'trail_price': trail_price,
            'trail_distance': trail_distance,
            'trail_distance_pct': trail_pct,
            'locked_profit_pct': locked_profit_pct
        }

    def can_open_position(self, position_size_usd):
        """
        Check if new position can be opened based on risk limits.

        Args:
            position_size_usd: Proposed position size in USD

        Returns:
            dict: {
                'can_open': bool,
                'reason': str,
                'current_exposure': float,
                'max_exposure': float,
                'daily_pnl': float,
                'current_drawdown': float
            }
        """
        # Check daily loss limit
        daily_loss_pct = self.daily_pnl / self.account_balance if self.account_balance > 0 else 0
        if daily_loss_pct <= -self.max_daily_loss:
            return {
                'can_open': False,
                'reason': f'Max daily loss reached ({daily_loss_pct*100:.2f}% / {self.max_daily_loss*100:.1f}%)',
                'current_exposure': self.total_exposure,
                'max_exposure': self.max_total_exposure,
                'daily_pnl': self.daily_pnl,
                'current_drawdown': self.current_drawdown
            }

        # Check max drawdown
        if self.current_drawdown >= self.max_drawdown:
            return {
                'can_open': False,
                'reason': f'Max drawdown reached ({self.current_drawdown*100:.2f}% / {self.max_drawdown*100:.1f}%)',
                'current_exposure': self.total_exposure,
                'max_exposure': self.max_total_exposure,
                'daily_pnl': self.daily_pnl,
                'current_drawdown': self.current_drawdown
            }

        # Check total exposure limit
        new_exposure = self.total_exposure + position_size_usd
        exposure_pct = new_exposure / self.account_balance if self.account_balance > 0 else 0

        if exposure_pct > self.max_total_exposure:
            return {
                'can_open': False,
                'reason': f'Max exposure limit ({exposure_pct*100:.1f}% > {self.max_total_exposure*100:.1f}%)',
                'current_exposure': self.total_exposure,
                'max_exposure': self.max_total_exposure,
                'daily_pnl': self.daily_pnl,
                'current_drawdown': self.current_drawdown
            }

        return {
            'can_open': True,
            'reason': 'All risk checks passed',
            'current_exposure': self.total_exposure,
            'max_exposure': self.max_total_exposure,
            'daily_pnl': self.daily_pnl,
            'current_drawdown': self.current_drawdown
        }

    def add_position(self, symbol, entry_price, size_usd, direction, stop_price):
        """
        Add a new open position to tracking.

        Args:
            symbol: Trading symbol
            entry_price: Entry price
            size_usd: Position size in USD
            direction: 'long' or 'short'
            stop_price: Stop-loss price
        """
        position = {
            'symbol': symbol,
            'entry_price': entry_price,
            'size_usd': size_usd,
            'direction': direction,
            'stop_price': stop_price,
            'entry_time': datetime.utcnow(),
            'highest_price': entry_price,
            'tp1_hit': False,
            'tp2_hit': False,
            'tp3_hit': False,
            'remaining_size': 1.0  # Percentage remaining
        }

        self.open_positions.append(position)
        self.total_exposure += size_usd

    def remove_position(self, symbol):
        """
        Remove a position from tracking.

        Args:
            symbol: Trading symbol
        """
        for i, pos in enumerate(self.open_positions):
            if pos['symbol'] == symbol:
                self.total_exposure -= pos['size_usd'] * pos['remaining_size']
                self.open_positions.pop(i)
                break

    def update_position_pnl(self, symbol, current_price, pnl_usd):
        """
        Update position PnL and daily PnL tracking.

        Args:
            symbol: Trading symbol
            current_price: Current market price
            pnl_usd: Position PnL in USD
        """
        # Update position's highest/lowest price
        for pos in self.open_positions:
            if pos['symbol'] == symbol:
                if pos['direction'] == 'long':
                    pos['highest_price'] = max(pos['highest_price'], current_price)
                else:
                    pos['highest_price'] = min(pos['highest_price'], current_price)
                break

    def record_closed_trade(self, pnl_usd):
        """
        Record PnL from a closed trade.

        Args:
            pnl_usd: Trade PnL in USD
        """
        self.daily_pnl += pnl_usd
        self.update_balance(self.account_balance + pnl_usd)
