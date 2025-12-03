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
            "sell_signal": False
        }
    
    vwap = calculate_vwap(df)
    rsi = calculate_rsi(df)
    macd_line, signal_line, hist = calculate_macd(df)

    buy_signal = (df['close'].iloc[-1] > vwap.iloc[-1]) and (rsi.iloc[-1] < 70) and (macd_line.iloc[-1] > signal_line.iloc[-1])
    sell_signal = (df['close'].iloc[-1] < vwap.iloc[-1]) and (rsi.iloc[-1] > 30) and (macd_line.iloc[-1] < signal_line.iloc[-1])

    return {
        "vwap": vwap,
        "rsi": rsi,
        "macd_line": macd_line,
        "signal_line": signal_line,
        "histogram": hist,
        "buy_signal": buy_signal,
        "sell_signal": sell_signal
    }
