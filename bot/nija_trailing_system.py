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

# Import scalar helper for indicator conversions
try:
    from indicators import scalar
except ImportError:
    # Fallback if indicators.py is not available
    def scalar(x):
        if isinstance(x, (tuple, list)):
            return float(x[0])
        return float(x)

class NIJATrailingSystem:
    """
    NIJA Trailing System for advanced position management
    """

    def clear_all_positions(self):
        """Close and remove all open positions (manual and NIJA)"""
        self.positions.clear()
    
    def __init__(self):
        self.positions = {}  # Track open positions
        
    def calculate_ema(self, df, period=21):
        """Calculate EMA-21"""
        return df['close'].ewm(span=period, adjust=False).mean()
    
    def get_base_stop_loss(self, entry_price, side, volatility=0.004):
        """
        Calculate base stop-loss: 0.5% - 0.7% from entry (balanced for small accounts)
        Higher volatility = wider stop
        """
        # Base: 0.5%, adjusts up to 0.7% based on volatility
        stop_distance = 0.005 + (volatility * 5)  # 0.5% + volatility adjustment
        stop_distance = min(stop_distance, 0.007)  # Cap at 0.7%
        
        if side == 'long':
            return entry_price * (1 - stop_distance)
        else:  # short
            return entry_price * (1 + stop_distance)
    
    def calculate_trailing_stop(self, position, current_price, ema_21, current_profit_pct):
        """
        NIJA Trailing Stop-Loss (TSL) - Fast Scalp Protection
        
        Activated at TP1 (+0.8%)
        Tighter trails for faster profit capture
        """
        side = position['side']
        entry_price = position['entry_price']
        
        # Not activated until TP1 (+0.8%) hits
        if current_profit_pct < 0.8:
            return position['stop_loss']
        
        # A. EMA-21 Dynamic Trail (looser - use EMA-21 minus buffer)
        if side == 'long':
            ema_stop = ema_21 * 0.995  # 0.5% below EMA-21 (more room)
        else:
            ema_stop = ema_21 * 1.005  # 0.5% above EMA-21
        
        # B. Percentage-Based Trail - TIGHT for fast scalps
        if current_profit_pct > 3.0:
            trail_pct = 0.005  # 0.5% trail (lock massive winners)
        elif current_profit_pct > 2.0:
            trail_pct = 0.01   # 1.0% trail
        elif current_profit_pct > 1.0:
            trail_pct = 0.015  # 1.5% trail
        else:
            trail_pct = 0.02   # 2.0% trail (default - tighter)
        
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
        
        # Convert indicators to scalar values
        rsi = scalar(rsi)
        vwap = scalar(vwap)
        
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
        if pullback_from_peak > 0.8:  # 0.8% pullback from peak (less sensitive)
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
        
        # Convert indicators to scalar values
        rsi = scalar(rsi)
        vwap = scalar(vwap)
        
        # Calculate current profit
        if side == 'long':
            profit_pct = ((current_price - entry_price) / entry_price) * 100
        else:
            profit_pct = ((entry_price - current_price) / entry_price) * 100
        
        position['profit_pct'] = profit_pct
        
        # Get EMA-21
        ema_21 = self.calculate_ema(df).iloc[-1]
        
        # PEAK PROFIT TRACKING: Track highest profit achieved
        if 'peak_profit_pct' not in position:
            position['peak_profit_pct'] = profit_pct
        
        # Update peak profit if current profit is higher
        if profit_pct > position['peak_profit_pct']:
            position['peak_profit_pct'] = profit_pct
        
        # PROFIT LOCK: Never give back more than 0.5% of peak profit
        # Example: Peak 3% → Drops to 2.5% → Auto-exit to lock in 2.5%
        if profit_pct >= 0.25:
            # Calculate giveback from peak
            giveback_pct = position['peak_profit_pct'] - profit_pct
            
            # Exit if giving back more than 0.5% (with small epsilon for floating point comparison)
            GIVEBACK_THRESHOLD = 0.5
            EPSILON = 0.001  # 0.001% tolerance for floating point errors
            if giveback_pct > (GIVEBACK_THRESHOLD + EPSILON):
                return 'close_all', position['remaining_size'], f"Auto-exit: Giveback {giveback_pct:.2f}% from peak {position['peak_profit_pct']:.2f}% (locked at +{profit_pct:.2f}%)"
            
            # Lock in current profit minus 0.5% buffer
            locked_profit = position['peak_profit_pct'] - 0.5
            profit_lock_stop = entry_price * (1 + locked_profit / 100) if side == 'long' else entry_price * (1 - locked_profit / 100)
            
            # Use the better stop (initial stop or profit lock)
            if side == 'long':
                position['stop_loss'] = max(position['stop_loss'], profit_lock_stop)
            else:
                position['stop_loss'] = min(position['stop_loss'], profit_lock_stop)
            
            if not position.get('profit_lock_active', False):
                position['profit_lock_active'] = True
                print(f"   🔒 Profit lock active: Allow max 0.5% giveback from peak (stop at +{locked_profit:.2f}%)")
        
        # Calculate trailing stop
        new_stop = self.calculate_trailing_stop(position, current_price, ema_21, profit_pct)
        position['stop_loss'] = new_stop
        
        # Check if stop hit
        if side == 'long' and current_price <= position['stop_loss']:
            return 'close_all', position['remaining_size'], f"Stop-loss hit at {position['stop_loss']:.2f}"
        elif side == 'short' and current_price >= position['stop_loss']:
            return 'close_all', position['remaining_size'], f"Stop-loss hit at {position['stop_loss']:.2f}"
        
        # FAST PROFIT CAPTURE: TP0.5 at +0.4% → Close 30% (ultra-fast scalp)
        if profit_pct >= 0.4 and position['remaining_size'] == 1.0 and not position.get('tp05_hit', False):
            position['remaining_size'] = 0.70
            position['tp05_hit'] = True
            return 'partial_close', 0.30, f"TP0.5 hit (+{profit_pct:.2f}%) - Fast scalp lock"
        
        # TP1: +0.8% → Close 30% more (60% total out)
        if profit_pct >= 0.8 and position['remaining_size'] == 0.70 and not position.get('tp1_hit', False):
            position['remaining_size'] = 0.40
            position['tsl_active'] = True
            position['tp1_hit'] = True
            return 'partial_close', 0.30, f"TP1 hit (+{profit_pct:.2f}%) - TSL activated"
        
        # TP2: +1.5% → Close 20% more (20% remaining)
        if profit_pct >= 1.5 and position['remaining_size'] == 0.40 and not position.get('tp2_hit', False):
            position['remaining_size'] = 0.20
            position['ttp_active'] = True
            position['tp2_hit'] = True
            return 'partial_close', 0.20, f"TP2 hit (+{profit_pct:.2f}%) - TTP activated"
        
        # TP3: Extended runner zone - let winners run to 20% with 95% lock protection
        if profit_pct >= 2.5 and position['remaining_size'] == 0.20:
            # Check momentum - if strong, keep riding
            avg_volume = df['volume'].rolling(20).mean().iloc[-1]
            current_volume = df['volume'].iloc[-1]
            
            # Strong momentum conditions
            strong_momentum = (
                (side == 'long' and rsi > 50 and current_volume > avg_volume * 1.0) or
                (side == 'short' and rsi < 50 and current_volume > avg_volume * 1.0)
            )
            
            if strong_momentum and profit_pct < 10.0:  # Let runners develop to 10%
                return 'hold', 0, f"TP3+ zone - Strong momentum, trailing (RSI={rsi:.1f}, Vol={current_volume/avg_volume:.1f}x)"
            elif profit_pct >= 10.0 and profit_pct < 20.0:
                # MEGA WINNER - keep trailing with 95% lock until 20%
                return 'hold', 0, f"🚀 MEGA WINNER +{profit_pct:.2f}% - Trailing (95% locked at +{profit_pct*0.95:.2f}%)"
            elif profit_pct >= 20.0:
                # Exit at 20% cap - reinvest into new opportunities
                return 'hold', 0, f"💎 DIAMOND HAND +{profit_pct:.2f}% - Trailing to exit"
        
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
    
    def open_position(self, position_id, side, entry_price, size, volatility=0.004, market_params=None, scale_in=False):
        """Open a new NIJA position with market-specific parameters
        
        Args:
            scale_in: If True, this is adding to an existing winning position (pyramiding)
        """
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
