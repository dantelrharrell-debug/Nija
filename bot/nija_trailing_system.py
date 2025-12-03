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
        NIJA Trailing Stop-Loss (TSL) - Optimized for Riding Trends
        
        Activated at TP1 (+0.5%)
        Uses LOOSE trails to let winners run to peak
        """
        side = position['side']
        entry_price = position['entry_price']
        
        # Not activated until TP1 (+0.5%) hits
        if current_profit_pct < 0.5:
            return position['stop_loss']
        
        # A. EMA-21 Dynamic Trail (looser - use EMA-21 minus buffer)
        if side == 'long':
            ema_stop = ema_21 * 0.995  # 0.5% below EMA-21 (more room)
        else:
            ema_stop = ema_21 * 1.005  # 0.5% above EMA-21
        
        # B. Percentage-Based Trail - MUCH LOOSER for trend riding
        if current_profit_pct > 5.0:
            trail_pct = 0.003  # 0.30% trail (massive winners get tight)
        elif current_profit_pct > 3.0:
            trail_pct = 0.005  # 0.50% trail
        elif current_profit_pct > 2.0:
            trail_pct = 0.008  # 0.80% trail
        elif current_profit_pct > 1.0:
            trail_pct = 0.01   # 1.0% trail
        else:
            trail_pct = 0.012  # 1.2% trail (default after TP1 - very loose)
        
        if side == 'long':
            percentage_stop = current_price * (1 - trail_pct)
            # Use tighter (higher) stop
            trailing_stop = max(ema_stop, percentage_stop, position['stop_loss'])
        else:  # short
            percentage_stop = current_price * (1 + trail_pct)
            # Use tighter (lower) stop
            trailing_stop = min(ema_stop, percentage_stop, position['stop_loss'])
        
        return trailing_stop
    
    def check_trailing_take_profit(self, position, current_candle, prev_candle, rsi, vwap, df):
        """
        NIJA Trailing Take-Profit (TTP) - Peak Detection System
        
        Activated after TP2 (+1%)
        Detects peaks using multiple confluence signals
        """
        side = position['side']
        current_price = current_candle['close']
        profit_pct = position['profit_pct']
        
        # Not activated until TP2 (+1%) hits and 25% remaining
        if position['remaining_size'] > 0.25 or profit_pct < 1.0:
            return False, None
        
        # Initialize tracking if needed
        if 'peak_price' not in position:
            position['peak_price'] = current_price
            position['peak_rsi'] = rsi
        
        # Update peak tracking
        if side == 'long' and current_price > position['peak_price']:
            position['peak_price'] = current_price
            position['peak_rsi'] = rsi
        elif side == 'short' and current_price < position['peak_price']:
            position['peak_price'] = current_price
            position['peak_rsi'] = rsi
        
        # Calculate pullback from peak
        if side == 'long':
            pullback_from_peak = ((position['peak_price'] - current_price) / position['peak_price']) * 100
        else:
            pullback_from_peak = ((current_price - position['peak_price']) / position['peak_price']) * 100
        
        # PEAK DETECTION SIGNALS
        peak_signals = 0
        
        # A. Strong Candle Pullback (price retracing from peak)
        if pullback_from_peak > 0.3:  # 0.3% pullback from peak
            peak_signals += 1
            
        # B. RSI Divergence (price higher but RSI lower = weakening)
        if side == 'long':
            if rsi < position['peak_rsi'] - 5 and current_price >= position['peak_price'] * 0.998:
                peak_signals += 1
        else:
            if rsi > position['peak_rsi'] + 5 and current_price <= position['peak_price'] * 1.002:
                peak_signals += 1
        
        # C. RSI Extreme Reversal (stronger signal)
        prev_rsi = position.get('prev_rsi', rsi)
        if side == 'long':
            if rsi > 75 and prev_rsi > rsi:  # Overbought and falling
                peak_signals += 1
        else:
            if rsi < 25 and prev_rsi < rsi:  # Oversold and rising
                peak_signals += 1
        
        # D. VWAP Shift (trend change)
        prev_price = position.get('prev_price', current_price)
        if side == 'long':
            if current_price < vwap and prev_price >= vwap:
                peak_signals += 1
        else:
            if current_price > vwap and prev_price <= vwap:
                peak_signals += 1
        
        # E. Volume Declining (momentum fading)
        if len(df) >= 3:
            avg_volume = df['volume'].rolling(5).mean().iloc[-1]
            if current_candle['volume'] < avg_volume * 0.7:  # Volume 30% below avg
                peak_signals += 1
        
        # Update previous values
        position['prev_rsi'] = rsi
        position['prev_price'] = current_price
        
        # EXIT if 2+ peak signals (confluence)
        if peak_signals >= 2:
            return True, f"Peak detected ({peak_signals} signals) - Pullback: {pullback_from_peak:.2f}%, RSI: {rsi:.1f}"
        
        # Don't exit if still strong momentum
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
        
        # TP3: Let it RUN! Only exit on peak detection, no arbitrary limits
        if profit_pct >= 1.5 and position['remaining_size'] == 0.25:
            # Check momentum - if strong, keep riding
            avg_volume = df['volume'].rolling(20).mean().iloc[-1]
            current_volume = df['volume'].iloc[-1]
            
            # Strong momentum conditions
            strong_momentum = (
                (side == 'long' and rsi > 55 and current_volume > avg_volume * 1.2) or
                (side == 'short' and rsi < 45 and current_volume > avg_volume * 1.2)
            )
            
            if strong_momentum and profit_pct < 5.0:  # Let it run up to 5%!
                return 'hold', 0, f"TP3+ zone - Strong momentum, trailing (RSI={rsi:.1f}, Vol={current_volume/avg_volume:.1f}x)"
            elif profit_pct >= 5.0:
                # Massive winner - only exit on peak signals, not arbitrary target
                return 'hold', 0, f"MASSIVE WINNER +{profit_pct:.2f}% - Trailing to peak"
        
        # Check TTP rules if active (peak detection)
        if position.get('ttp_active', False) and len(df) >= 2:
            should_exit, reason = self.check_trailing_take_profit(
                position, 
                df.iloc[-1], 
                df.iloc[-2], 
                rsi, 
                vwap,
                df
            )
            if should_exit:
                return 'close_all', position['remaining_size'], reason
        
        return 'hold', 0, f"Trailing (+{profit_pct:.2f}%) - Stop at {new_stop:.2f}"
    
    def open_position(self, position_id, side, entry_price, size, volatility=0.004, market_params=None):
        """Open a new NIJA position with market-specific parameters"""
        # Use market parameters if provided, otherwise use default crypto params
        if market_params:
            # Calculate stop using market-specific ranges
            stop_distance = market_params.sl_min + (volatility * 10)
            stop_distance = min(stop_distance, market_params.sl_max)
            
            if side == 'long':
                stop_loss = entry_price * (1 - stop_distance)
            else:
                stop_loss = entry_price * (1 + stop_distance)
        else:
            # Default crypto behavior
            stop_loss = self.get_base_stop_loss(entry_price, side, volatility)
        
        self.positions[position_id] = {
            'side': side,
            'entry_price': entry_price,
            'size': size,
            'remaining_size': 1.0,  # 100% initially
            'stop_loss': stop_loss,
            'tsl_active': False,
            'ttp_active': False,
            'profit_pct': 0.0,
            'opened_at': datetime.now(),
            'market_params': market_params  # Store for later use
        }
        return self.positions[position_id]
    
    def close_position(self, position_id):
        """Close and remove position"""
        if position_id in self.positions:
            del self.positions[position_id]
