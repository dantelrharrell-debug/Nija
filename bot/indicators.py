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
    Calculate VWAP, RSI, MACD and generate buy/sell signals
    """
    if len(df) < 30:
        return {
            "vwap": None,
            "rsi": None,
            "macd_line": None,
            "signal_line": None,
            "histogram": None,
            "buy_signal": False,
            "sell_signal": False,
            "no_trade_zone": False,
            "no_trade_reason": None
        }
    
    vwap = calculate_vwap(df)
    rsi = calculate_rsi(df)
    macd_line, signal_line, hist = calculate_macd(df)
    
    # Check no-trade zones
    is_no_trade, reason = check_no_trade_zones(df, rsi)

    buy_signal = (df['close'].iloc[-1] > vwap.iloc[-1]) and (rsi.iloc[-1] < 70) and (macd_line.iloc[-1] > signal_line.iloc[-1])
    sell_signal = (df['close'].iloc[-1] < vwap.iloc[-1]) and (rsi.iloc[-1] > 30) and (macd_line.iloc[-1] < signal_line.iloc[-1])

    return {
        "vwap": vwap,
        "rsi": rsi,
        "macd_line": macd_line,
        "signal_line": signal_line,
        "histogram": hist,
        "buy_signal": buy_signal,
        "sell_signal": sell_signal,
        "no_trade_zone": is_no_trade,
        "no_trade_reason": reason
    }
