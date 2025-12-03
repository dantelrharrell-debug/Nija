# nija_trailing_system.py
"""
NIJA TRAILING SYSTEM™
Dynamic. Aggressive. Protected.

Implements:
- NIJA Trailing Stop-Loss (TSL) with EMA-21 and percentage-based micro-trail
- NIJA Trailing Take-Profit (TTP) with candle pullback, momentum, and VWAP rules
- Partial position management (TP1: 50%, TP2: 25%, TP3: 25%)
"""

import pandas as pd
from datetime import datetime

class NIJATrailingSystem:
    """
    NIJA Trailing System for advanced position management
    """
    
    def __init__(self):
        self.positions = {}  # Track open positions
        
    def calculate_ema(self, df, period=21):
        """Calculate EMA-21"""
        return df['close'].ewm(span=period, adjust=False).mean()
    
    def get_base_stop_loss(self, entry_price, side, volatility=0.004):
        """
        Calculate base stop-loss: 0.35% - 0.50% from entry (NIJA DEFAULT)
        Higher volatility = wider stop
        """
        # Base: 0.35%, adjusts up to 0.50% based on volatility
        stop_distance = 0.0035 + (volatility * 10)  # 0.35% + volatility adjustment
        stop_distance = min(stop_distance, 0.005)  # Cap at 0.50%
        
        if side == 'long':
            return entry_price * (1 - stop_distance)
        else:  # short
            return entry_price * (1 + stop_distance)
    
    def calculate_trailing_stop(self, position, current_price, ema_21, current_profit_pct):
        """
        NIJA Trailing Stop-Loss (TSL)
        
        Activated at TP1 (+0.5%)
        Uses max(EMA-21 trail, percentage trail)
        """
        side = position['side']
        entry_price = position['entry_price']
        
        # Not activated until TP1 (+0.5%) hits
        if current_profit_pct < 0.5:
            return position['stop_loss']
        
        # A. EMA-21 Dynamic Trail
        ema_stop = ema_21
        
        # B. Percentage-Based Micro-Trail
        if current_profit_pct > 2.0:
            trail_pct = 0.001  # 0.10% trail
        elif current_profit_pct > 1.5:
            trail_pct = 0.0015  # 0.15% trail
        elif current_profit_pct > 1.0:
            trail_pct = 0.0025  # 0.25% trail
        else:
            trail_pct = 0.0025  # 0.25% trail (default after TP1)
        
        if side == 'long':
            percentage_stop = current_price * (1 - trail_pct)
            # Use tighter (higher) stop
            trailing_stop = max(ema_stop, percentage_stop, position['stop_loss'])
        else:  # short
            percentage_stop = current_price * (1 + trail_pct)
            # Use tighter (lower) stop
            trailing_stop = min(ema_stop, percentage_stop, position['stop_loss'])
        
        return trailing_stop
    
    def check_trailing_take_profit(self, position, current_candle, prev_candle, rsi, vwap):
        """
        NIJA Trailing Take-Profit (TTP)
        
        Activated after TP2 (+1%)
        Uses candle pullback, RSI momentum, and VWAP shift rules
        """
        side = position['side']
        current_price = current_candle['close']
        
        # Not activated until TP2 (+1%) hits and 25% remaining
        if position['remaining_size'] > 0.25 or position['profit_pct'] < 1.0:
            return False, None
        
        # A. Candle Pullback Rule
        if side == 'long':
            if current_candle['close'] < prev_candle['low']:
                return True, "Candle pullback (close < prev low)"
        else:  # short
            if current_candle['close'] > prev_candle['high']:
                return True, "Candle pullback (close > prev high)"
        
        # B. Momentum Exit Rule
        if side == 'long':
            if rsi > 70 and position.get('prev_rsi', rsi) > rsi:
                return True, f"RSI momentum reversal (RSI={rsi:.1f})"
        else:  # short
            if rsi < 30 and position.get('prev_rsi', rsi) < rsi:
                return True, f"RSI momentum reversal (RSI={rsi:.1f})"
        
        # C. VWAP Shift Rule
        if side == 'long':
            if current_price < vwap and position.get('prev_price', current_price) > vwap:
                return True, f"VWAP cross below (price={current_price:.2f}, vwap={vwap:.2f})"
        else:  # short
            if current_price > vwap and position.get('prev_price', current_price) < vwap:
                return True, f"VWAP cross above (price={current_price:.2f}, vwap={vwap:.2f})"
        
        # Update previous values for next check
        position['prev_rsi'] = rsi
        position['prev_price'] = current_price
        
        return False, None
    
    def manage_position(self, position_id, current_price, df, rsi, vwap):
        """
        Full NIJA position management flow
        
        Returns: (action, size_to_close, reason)
        """
        if position_id not in self.positions:
            return None, 0, None
        
        position = self.positions[position_id]
        side = position['side']
        entry_price = position['entry_price']
        
        # Calculate current profit
        if side == 'long':
            profit_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            profit_pct = ((entry_price - current_price) / entry_price) * 100
        
        position['profit_pct'] = profit_pct
        
        # Get EMA-21
        ema_21 = self.calculate_ema(df).iloc[-1]
        
        # Calculate trailing stop
        new_stop = self.calculate_trailing_stop(position, current_price, ema_21, profit_pct)
        position['stop_loss'] = new_stop
        
        # Check if stop hit
        if side == 'long' and current_price <= position['stop_loss']:
            return 'close_all', position['remaining_size'], f"Stop-loss hit at {position['stop_loss']:.2f}"
        elif side == 'short' and current_price >= position['stop_loss']:
            return 'close_all', position['remaining_size'], f"Stop-loss hit at {position['stop_loss']:.2f}"
        
        # TP1: +0.5% → Close 50%
        if profit_pct >= 0.5 and position['remaining_size'] == 1.0:
            position['remaining_size'] = 0.5
            position['tsl_active'] = True
            return 'partial_close', 0.5, f"TP1 hit (+{profit_pct:.2f}%) - TSL activated"
        
        # TP2: +1.0% → Close 25%
        if profit_pct >= 1.0 and position['remaining_size'] == 0.5:
            position['remaining_size'] = 0.25
            position['ttp_active'] = True
            return 'partial_close', 0.25, f"TP2 hit (+{profit_pct:.2f}%) - TTP activated"
        
        # TP3: +1.5-2.0% → Close final 25% OR keep trailing
        if profit_pct >= 1.5 and position['remaining_size'] == 0.25:
            # Check if momentum is insane (keep riding to 2%)
            if profit_pct < 2.0 and rsi > 60 and df['volume'].iloc[-1] > df['volume'].rolling(20).mean().iloc[-1] * 1.5:
                return 'hold', 0, f"TP3 zone - momentum strong, trailing to 2% (RSI={rsi:.1f})"
            else:
                return 'close_all', 0.25, f"TP3 hit (+{profit_pct:.2f}%) - Final exit"
        
        # Check TTP rules if active
        if position.get('ttp_active', False) and len(df) >= 2:
            should_exit, reason = self.check_trailing_take_profit(
                position, 
                df.iloc[-1], 
                df.iloc[-2], 
                rsi, 
                vwap
            )
            if should_exit:
                return 'close_all', position['remaining_size'], reason
        
        return 'hold', 0, f"Trailing (+{profit_pct:.2f}%) - Stop at {new_stop:.2f}"
    
    def open_position(self, position_id, side, entry_price, size, volatility=0.004):
        """Open a new NIJA position"""
        self.positions[position_id] = {
            'side': side,
            'entry_price': entry_price,
            'size': size,
            'remaining_size': 1.0,  # 100% initially
            'stop_loss': self.get_base_stop_loss(entry_price, side, volatility),
            'tsl_active': False,
            'ttp_active': False,
            'profit_pct': 0.0,
            'opened_at': datetime.now()
        }
        return self.positions[position_id]
    
    def close_position(self, position_id):
        """Close and remove position"""
        if position_id in self.positions:
            del self.positions[position_id]
