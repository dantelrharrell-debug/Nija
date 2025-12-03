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
    # ❌ 1m chart extreme RSI > 90 or < 10
    if rsi.iloc[-1] > 90:
        return True, "Extreme RSI > 90"
    if rsi.iloc[-1] < 10:
        return True, "Extreme RSI < 10"
    
    # ❌ Low-volume consolidation
    avg_volume = df['volume'].rolling(20).mean().iloc[-1]
    if df['volume'].iloc[-1] < avg_volume * 0.3:
        return True, "Low volume consolidation"
    
    # ❌ Large unpredictable wicks (wick > 2x body)
    last_candle = df.iloc[-1]
    body = abs(last_candle['close'] - last_candle['open'])
    upper_wick = last_candle['high'] - max(last_candle['close'], last_candle['open'])
    lower_wick = min(last_candle['close'], last_candle['open']) - last_candle['low']
    
    if body > 0 and (upper_wick > body * 2 or lower_wick > body * 2):
        return True, "Large unpredictable wicks"
    
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
    # NIJA LONG ENTRY CONDITIONS (All must be TRUE)
    # ═══════════════════════════════════════════════════════════
    
    long_conditions = {
        "price_above_vwap": current_price > vwap.iloc[-1],
        "ema_alignment": ema_9.iloc[-1] > ema_21.iloc[-1] > ema_50.iloc[-1],
        "rsi_cross_above_30": prev_rsi <= 30 and current_rsi > 30,
        "volume_confirmation": current_volume >= prev_2_volume,
        "candle_close_bullish": current_price > prev_price
    }
    
    buy_signal = all(long_conditions.values())
    
    # ═══════════════════════════════════════════════════════════
    # NIJA SHORT ENTRY CONDITIONS (All must be TRUE)
    # ═══════════════════════════════════════════════════════════
    
    short_conditions = {
        "price_below_vwap": current_price < vwap.iloc[-1],
        "ema_alignment": ema_9.iloc[-1] < ema_21.iloc[-1] < ema_50.iloc[-1],
        "rsi_cross_below_70": prev_rsi >= 70 and current_rsi < 70,
        "volume_confirmation": current_volume >= prev_2_volume,
        "candle_close_bearish": current_price < prev_price
    }
    
    sell_signal = all(short_conditions.values())
    
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
        "no_trade_zone": is_no_trade,
        "no_trade_reason": reason,
        "entry_conditions": {
            "long": long_conditions,
            "short": short_conditions
        }
    }
