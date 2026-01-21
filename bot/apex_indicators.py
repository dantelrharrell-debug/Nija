"""
NIJA Apex Strategy v7.1 - Technical Indicators
================================================

Advanced technical indicators for the Apex trading strategy including:
- ADX (Average Directional Index) for trend strength
- ATR (Average True Range) for volatility measurement
- Enhanced MACD with histogram analysis
- Swing high/low detection for stop loss placement
- Volume analysis
"""

import pandas as pd
import numpy as np


def scalar(x):
    """
    Convert indicator value to float.
    
    Defensive helper to handle cases where indicators may return tuples/lists
    instead of scalar values. This prevents comparison bugs.
    
    Args:
        x: Indicator value (could be float, int, tuple, list, or pandas Series)
        
    Returns:
        float: Scalar float value
        
    Examples:
        >>> scalar(25.5)
        25.5
        >>> scalar((25.5, 30.0))
        25.5
        >>> scalar([25.5, 30.0])
        25.5
        
    Raises:
        ValueError: If tuple/list is empty
    """
    if isinstance(x, (tuple, list)):
        if len(x) == 0:
            raise ValueError("Cannot convert empty tuple/list to scalar")
        return float(x[0])
    return float(x)


def calculate_atr(df, period=14):
    """
    Calculate Average True Range (ATR)
    
    Args:
        df: DataFrame with high, low, close columns
        period: ATR period (default 14)
        
    Returns:
        Series with ATR values
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    # True Range calculation
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period, min_periods=period).mean()
    
    return atr.ffill().fillna(0)


def calculate_adx(df, period=14):
    """
    Calculate Average Directional Index (ADX)
    
    ADX measures trend strength regardless of direction.
    Values > 20 indicate trending market, > 40 indicates strong trend.
    
    Args:
        df: DataFrame with high, low, close columns
        period: ADX period (default 14)
        
    Returns:
        tuple: (adx, plus_di, minus_di)
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    # Calculate +DM and -DM
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)
    
    # Calculate ATR
    atr = calculate_atr(df, period)
    
    # Smooth +DM and -DM
    plus_dm_smooth = plus_dm.rolling(window=period, min_periods=period).mean()
    minus_dm_smooth = minus_dm.rolling(window=period, min_periods=period).mean()
    
    # Calculate +DI and -DI
    plus_di = 100 * (plus_dm_smooth / atr)
    minus_di = 100 * (minus_dm_smooth / atr)
    
    # Calculate DX
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    
    # Calculate ADX (smoothed DX)
    adx = dx.rolling(window=period, min_periods=period).mean()
    
    return adx.ffill().fillna(0), plus_di.ffill().fillna(0), minus_di.ffill().fillna(0)


def calculate_enhanced_macd(df, fast=12, slow=26, signal=9):
    """
    Calculate MACD with enhanced histogram analysis
    
    Args:
        df: DataFrame with close prices
        fast: Fast EMA period (default 12)
        slow: Slow EMA period (default 26)
        signal: Signal line period (default 9)
        
    Returns:
        tuple: (macd_line, signal_line, histogram, histogram_direction)
    """
    close = df['close']
    
    # Calculate MACD
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    
    # Signal line
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    
    # Histogram
    histogram = macd_line - signal_line
    
    # Histogram direction (1 for growing, -1 for shrinking, 0 for flat)
    histogram_direction = np.sign(histogram.diff())
    
    return (
        macd_line.ffill(),
        signal_line.ffill(),
        histogram.ffill(),
        pd.Series(histogram_direction, index=df.index).fillna(0)
    )


def find_swing_low(df, lookback=5):
    """
    Find the most recent swing low for stop loss placement
    
    Args:
        df: DataFrame with low prices
        lookback: Number of candles to look back
        
    Returns:
        float: Swing low price
    """
    if len(df) < lookback:
        return df['low'].min()
    
    recent_lows = df['low'].tail(lookback)
    return recent_lows.min()


def find_swing_high(df, lookback=5):
    """
    Find the most recent swing high for stop loss placement
    
    Args:
        df: DataFrame with high prices
        lookback: Number of candles to look back
        
    Returns:
        float: Swing high price
    """
    if len(df) < lookback:
        return df['high'].max()
    
    recent_highs = df['high'].tail(lookback)
    return recent_highs.max()


def calculate_volume_average(df, period=20):
    """
    Calculate average volume over specified period
    
    Args:
        df: DataFrame with volume column
        period: Period for average (default 20)
        
    Returns:
        Series: Average volume
    """
    return df['volume'].rolling(window=period, min_periods=period).mean().ffill()


def is_volume_above_threshold(df, threshold=0.5):
    """
    Check if current volume is above threshold of recent average
    
    Args:
        df: DataFrame with volume column
        threshold: Threshold as decimal (0.5 = 50% of average)
        
    Returns:
        bool: True if volume is above threshold
    """
    if len(df) < 20:
        return False
    
    current_volume = df['volume'].iloc[-1]
    avg_volume = calculate_volume_average(df).iloc[-1]
    
    return current_volume >= (avg_volume * threshold)


def calculate_ema_alignment(df):
    """
    Calculate EMA alignment for trend confirmation
    
    Returns:
        dict: {
            'ema9': EMA9 values,
            'ema21': EMA21 values,
            'ema50': EMA50 values (if enough data),
            'bullish_alignment': bool,
            'bearish_alignment': bool
        }
    """
    close = df['close']
    
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    
    result = {
        'ema9': ema9,
        'ema21': ema21,
        'bullish_alignment': False,
        'bearish_alignment': False
    }
    
    # Check if we have enough data for EMA50
    if len(df) >= 50:
        ema50 = close.ewm(span=50, adjust=False).mean()
        result['ema50'] = ema50
        
        # Bullish: EMA9 > EMA21 > EMA50
        result['bullish_alignment'] = (
            ema9.iloc[-1] > ema21.iloc[-1] and 
            ema21.iloc[-1] > ema50.iloc[-1]
        )
        
        # Bearish: EMA9 < EMA21 < EMA50
        result['bearish_alignment'] = (
            ema9.iloc[-1] < ema21.iloc[-1] and 
            ema21.iloc[-1] < ema50.iloc[-1]
        )
    else:
        # Simplified alignment without EMA50
        result['bullish_alignment'] = ema9.iloc[-1] > ema21.iloc[-1]
        result['bearish_alignment'] = ema9.iloc[-1] < ema21.iloc[-1]
    
    return result


def calculate_vwap(df):
    """
    Calculate VWAP (Volume Weighted Average Price)
    
    Args:
        df: DataFrame with high, low, close, volume columns
        
    Returns:
        Series: VWAP values
    """
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    vwap = (typical_price * df['volume']).cumsum() / df['volume'].cumsum()
    return vwap.ffill().fillna(df['close'])


def calculate_rsi(df, period=14):
    """
    Calculate RSI (Relative Strength Index)
    
    Args:
        df: DataFrame with close prices
        period: RSI period (default 14)
        
    Returns:
        Series: RSI values
    """
    close = df['close']
    delta = close.diff()
    
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi.ffill().fillna(50)


def is_bullish_reversal_candle(df):
    """
    Detect bullish reversal candle pattern
    
    Args:
        df: DataFrame with OHLC data
        
    Returns:
        bool: True if current candle is bullish reversal
    """
    if len(df) < 2:
        return False
    
    current = df.iloc[-1]
    previous = df.iloc[-2]
    
    # Bullish candle (close > open)
    is_bullish = current['close'] > current['open']
    
    # Lower low than previous (pullback)
    lower_low = current['low'] < previous['low']
    
    # Strong close (close in upper 50% of range)
    range_size = current['high'] - current['low']
    if range_size > 0:
        close_position = (current['close'] - current['low']) / range_size
        strong_close = close_position >= 0.5
    else:
        strong_close = False
    
    return is_bullish and lower_low and strong_close


def is_bearish_reversal_candle(df):
    """
    Detect bearish reversal candle pattern
    
    Args:
        df: DataFrame with OHLC data
        
    Returns:
        bool: True if current candle is bearish reversal
    """
    if len(df) < 2:
        return False
    
    current = df.iloc[-1]
    previous = df.iloc[-2]
    
    # Bearish candle (close < open)
    is_bearish = current['close'] < current['open']
    
    # Higher high than previous (rejection)
    higher_high = current['high'] > previous['high']
    
    # Strong close (close in lower 50% of range)
    range_size = current['high'] - current['low']
    if range_size > 0:
        close_position = (current['close'] - current['low']) / range_size
        strong_close = close_position <= 0.5
    else:
        strong_close = False
    
    return is_bearish and higher_high and strong_close
