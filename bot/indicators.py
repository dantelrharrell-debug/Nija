# indicators.py
import pandas as pd

def calculate_vwap(df):
    q = df['volume']
    p = (df['high'] + df['low'] + df['close']) / 3
    vwap = (p * q).cumsum() / q.cumsum()
    return vwap.ffill().fillna(df['close'])

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.ffill().fillna(50)

def calculate_ema(df, period):
    """Calculate EMA for given period"""
    return df['close'].ewm(span=period, adjust=False).mean().ffill()

def calculate_macd(df, fast=12, slow=26, signal=9):
    exp1 = df['close'].ewm(span=fast, adjust=False).mean()
    exp2 = df['close'].ewm(span=slow, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line.ffill(), signal_line.ffill(), histogram.ffill()

def check_no_trade_zones(df, rsi):
    """
    Check if we're in a NO-TRADE ZONE
    
    Returns: (is_no_trade_zone, reason)
    """
    # ❌ Only extreme RSI > 98 or < 2 (ultra relaxed - almost never triggers)
    if rsi.iloc[-1] > 98:
        return True, "Extreme RSI > 98"
    if rsi.iloc[-1] < 2:
        return True, "Extreme RSI < 2"
    
    # ❌ Low-volume consolidation check DISABLED for testing
    # avg_volume = df['volume'].rolling(20).mean().iloc[-1]
    # if df['volume'].iloc[-1] < avg_volume * 0.05:
    #     return True, "Low volume consolidation (relaxed, 5% of avg)"

    # ❌ Low-liquidity pair (20-period avg volume < 500 units)
    if avg_volume < 500:
        return True, "Low-liquidity pair (avg volume < 500)"

    # ❌ Large unpredictable wicks (wick > 1.5x body)
    last_candle = df.iloc[-1]
    body = abs(last_candle['close'] - last_candle['open'])
    upper_wick = last_candle['high'] - max(last_candle['close'], last_candle['open'])
    lower_wick = min(last_candle['close'], last_candle['open']) - last_candle['low']

    if body > 0 and (upper_wick > body * 1.5 or lower_wick > body * 1.5):
        return True, "Large unpredictable wicks (stricter)"
    
    return False, None

def calculate_indicators(df):
    """
    NIJA ULTIMATE TRADING LOGIC™
    
    Calculate all indicators and generate precise entry signals based on:
    - VWAP (main trend filter)
    - RSI 14 (momentum trigger with CROSS detection)
    - EMA 9, 21, 50 (precision entry timing)
    - Volume confirmation (≥ previous 2 candles)
    - Candle close validation (bullish/bearish)
    """
    if len(df) < 51:  # Need 50+ for EMA-50
        return {
            "vwap": None,
            "rsi": None,
            "rsi_prev": None,
            "ema_9": None,
            "ema_21": None,
            "ema_50": None,
            "macd_line": None,
            "signal_line": None,
            "histogram": None,
            "buy_signal": False,
            "sell_signal": False,
            "no_trade_zone": False,
            "no_trade_reason": None,
            "entry_conditions": {}
        }
    
    # Calculate all indicators
    vwap = calculate_vwap(df)
    rsi = calculate_rsi(df, period=14)
    ema_9 = calculate_ema(df, 9)
    ema_21 = calculate_ema(df, 21)
    ema_50 = calculate_ema(df, 50)
    macd_line, signal_line, hist = calculate_macd(df)
    
    # Get current and previous values
    current_price = df['close'].iloc[-1]
    prev_price = df['close'].iloc[-2]
    current_rsi = rsi.iloc[-1]
    prev_rsi = rsi.iloc[-2]
    current_volume = df['volume'].iloc[-1]
    prev_2_volume = df['volume'].iloc[-2] + df['volume'].iloc[-3]
    
    # Check no-trade zones
    is_no_trade, reason = check_no_trade_zones(df, rsi)
    
    # ═══════════════════════════════════════════════════════════
    # NIJA LONG ENTRY CONDITIONS (Scored 1-5, need 2+ for entry)
    # Multi-Strategy: Momentum Breakout OR Pullback/Mean Reversion
    # ═══════════════════════════════════════════════════════════
    
    # Core trend conditions (must have these for quality)
    price_above_vwap = current_price > vwap.iloc[-1]
    ema_bullish = ema_9.iloc[-1] > ema_21.iloc[-1] > ema_50.iloc[-1]
    
    # RSI Strategy 1: Momentum (rising RSI)
    rsi_momentum_rising = current_rsi > prev_rsi and current_rsi < 80
    
    # RSI Strategy 2: Pullback/Mean Reversion (RSI cooling off in uptrend)
    # RSI 30-70 range, price still above VWAP, EMAs aligned = healthy pullback
    rsi_pullback = bool(30 < current_rsi < 70 and current_rsi < prev_rsi and price_above_vwap and ema_bullish)
    
    # Accept EITHER momentum OR pullback
    rsi_favorable = bool(rsi_momentum_rising or rsi_pullback)
    
    long_conditions = {
        "price_above_vwap": bool(price_above_vwap),
        "ema_alignment": bool(ema_bullish),
        "rsi_favorable": bool(rsi_favorable),  # Now accepts momentum OR pullback
        "volume_confirmation": bool(current_volume >= prev_2_volume * 0.5),
        "candle_close_bullish": bool(current_price > prev_price)
    }
    
    # Buy signal: require 3+ conditions for entry by default
    long_score = sum(long_conditions.values())
    buy_signal = long_score >= 3
    
    # ═══════════════════════════════════════════════════════════
    # NIJA SHORT ENTRY CONDITIONS (Scored 1-5, need 2+ for entry)
    # Multi-Strategy: Momentum Breakdown OR Bounce/Mean Reversion
    # ═══════════════════════════════════════════════════════════
    
    # Core trend conditions
    price_below_vwap = current_price < vwap.iloc[-1]
    ema_bearish = ema_9.iloc[-1] < ema_21.iloc[-1] < ema_50.iloc[-1]
    
    # RSI Strategy 1: Momentum (falling RSI)
    rsi_momentum_falling = current_rsi < prev_rsi and current_rsi > 20
    
    # RSI Strategy 2: Bounce/Mean Reversion (RSI bouncing in downtrend)
    rsi_bounce = bool(30 < current_rsi < 70 and current_rsi > prev_rsi and price_below_vwap and ema_bearish)
    
    # Accept EITHER momentum OR bounce
    rsi_favorable_short = bool(rsi_momentum_falling or rsi_bounce)
    
    short_conditions = {
        "price_below_vwap": bool(price_below_vwap),
        "ema_alignment": bool(ema_bearish),
        "rsi_favorable": bool(rsi_favorable_short),
        "volume_confirmation": bool(current_volume >= prev_2_volume * 0.5),
        "candle_close_bearish": bool(current_price < prev_price)
    }
    
    # Sell signal: require 3+ conditions for entry by default
    short_score = sum(short_conditions.values())
    sell_signal = short_score >= 3
    
    return {
        "vwap": vwap,
        "rsi": rsi,
        "rsi_prev": prev_rsi,
        "ema_9": ema_9,
        "ema_21": ema_21,
        "ema_50": ema_50,
        "macd_line": macd_line,
        "signal_line": signal_line,
        "histogram": hist,
        "buy_signal": buy_signal,
        "sell_signal": sell_signal,
        "long_score": long_score,
        "short_score": short_score,
        "no_trade_zone": is_no_trade,
        "no_trade_reason": reason,
        "entry_conditions": {
            "long": long_conditions,
            "short": short_conditions
        }
    }
