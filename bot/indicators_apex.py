"""
NIJA Apex Strategy v7.1 - Enhanced Indicators Module

Advanced technical indicators for NIJA Apex Strategy including:
- ADX (Average Directional Index) for trend strength
- ATR (Average True Range) for volatility measurement
- Enhanced MACD with histogram analysis
- Momentum candle pattern detection
- Volume analysis and filtering
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
    Calculate Average True Range (ATR) for volatility measurement.
    
    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        period: ATR period (default: 14)
    
    Returns:
        pandas.Series: ATR values
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    # Calculate True Range components
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    
    # True Range is the maximum of the three components
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # ATR is the smoothed average of True Range
    atr = tr.rolling(window=period, min_periods=period).mean()
    
    return atr.ffill().fillna(0)


def calculate_adx(df, period=14):
    """
    Calculate Average Directional Index (ADX) for trend strength.
    
    ADX > 25: Strong trend (good for trading)
    ADX < 20: Weak trend / choppy market (avoid trading)
    
    Args:
        df: DataFrame with 'high', 'low', 'close' columns
        period: ADX period (default: 14)
    
    Returns:
        tuple: (adx, plus_di, minus_di)
    """
    high = df['high']
    low = df['low']
    close = df['close']
    
    # Calculate +DM and -DM (Directional Movement)
    high_diff = high.diff()
    low_diff = -low.diff()
    
    plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0)
    minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0)
    
    # Calculate True Range
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Smooth the directional movements and true range
    atr = tr.rolling(window=period, min_periods=period).mean()
    plus_dm_smooth = plus_dm.rolling(window=period, min_periods=period).mean()
    minus_dm_smooth = minus_dm.rolling(window=period, min_periods=period).mean()
    
    # Calculate Directional Indicators
    plus_di = 100 * (plus_dm_smooth / atr)
    minus_di = 100 * (minus_dm_smooth / atr)
    
    # Calculate DX (Directional Index)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    
    # ADX is the smoothed average of DX
    adx = dx.rolling(window=period, min_periods=period).mean()
    
    return adx.ffill().fillna(0), plus_di.ffill().fillna(0), minus_di.ffill().fillna(0)


def calculate_macd_histogram_analysis(df, fast=12, slow=26, signal=9):
    """
    Calculate MACD with enhanced histogram analysis.
    
    Args:
        df: DataFrame with 'close' column
        fast: Fast EMA period (default: 12)
        slow: Slow EMA period (default: 26)
        signal: Signal line period (default: 9)
    
    Returns:
        dict: {
            'macd_line': MACD line,
            'signal_line': Signal line,
            'histogram': Histogram,
            'histogram_increasing': Boolean for increasing histogram,
            'bullish_cross': Boolean for bullish crossover,
            'bearish_cross': Boolean for bearish crossover
        }
    """
    exp1 = df['close'].ewm(span=fast, adjust=False).mean()
    exp2 = df['close'].ewm(span=slow, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    
    # Detect histogram direction
    histogram_increasing = histogram > histogram.shift(1)
    
    # Detect MACD line crosses
    bullish_cross = (macd_line > signal_line) & (macd_line.shift(1) <= signal_line.shift(1))
    bearish_cross = (macd_line < signal_line) & (macd_line.shift(1) >= signal_line.shift(1))
    
    return {
        'macd_line': macd_line.ffill(),
        'signal_line': signal_line.ffill(),
        'histogram': histogram.ffill(),
        'histogram_increasing': histogram_increasing,
        'bullish_cross': bullish_cross,
        'bearish_cross': bearish_cross
    }


def detect_momentum_candle(df, index=-1, volume_multiplier=1.2):
    """
    Detect momentum candle patterns for high-probability entries.
    
    A momentum candle is characterized by:
    - Strong directional move (body > 60% of total range)
    - Close near high/low (minimal wick on close side)
    - Above-average volume
    
    Args:
        df: DataFrame with OHLCV data
        index: Index to check (default: -1 for latest candle)
        volume_multiplier: Volume threshold multiplier (default: 1.2)
    
    Returns:
        dict: {
            'is_bullish_momentum': bool,
            'is_bearish_momentum': bool,
            'body_strength': float (0-1),
            'close_position': float (0-1, where close is in range)
        }
    """
    if len(df) < 2:
        return {
            'is_bullish_momentum': False,
            'is_bearish_momentum': False,
            'body_strength': 0,
            'close_position': 0.5
        }
    
    open_price = df['open'].iloc[index]
    high = df['high'].iloc[index]
    low = df['low'].iloc[index]
    close = df['close'].iloc[index]
    volume = df['volume'].iloc[index]
    avg_volume = df['volume'].rolling(window=20).mean().iloc[index]
    
    # Calculate candle metrics
    total_range = high - low
    body_size = abs(close - open_price)
    
    if total_range == 0:
        body_strength = 0
    else:
        body_strength = body_size / total_range
    
    # Close position in range (0 = at low, 1 = at high)
    if total_range == 0:
        close_position = 0.5
    else:
        close_position = (close - low) / total_range
    
    # Volume confirmation
    volume_strong = volume >= avg_volume * volume_multiplier if avg_volume > 0 else False
    
    # Bullish momentum: strong up candle with close near high
    is_bullish_momentum = (
        close > open_price and
        body_strength > 0.6 and
        close_position > 0.85 and
        volume_strong
    )
    
    # Bearish momentum: strong down candle with close near low
    is_bearish_momentum = (
        close < open_price and
        body_strength > 0.6 and
        close_position < 0.15 and
        volume_strong
    )
    
    return {
        'is_bullish_momentum': is_bullish_momentum,
        'is_bearish_momentum': is_bearish_momentum,
        'body_strength': body_strength,
        'close_position': close_position
    }


def check_ema_alignment(df, fast=9, medium=21, slow=50):
    """
    Check EMA alignment for trend confirmation.
    
    Args:
        df: DataFrame with 'close' column
        fast: Fast EMA period (default: 9)
        medium: Medium EMA period (default: 21)
        slow: Slow EMA period (default: 50)
    
    Returns:
        dict: {
            'bullish_aligned': bool (EMA9 > EMA21 > EMA50),
            'bearish_aligned': bool (EMA9 < EMA21 < EMA50),
            'ema_9': float,
            'ema_21': float,
            'ema_50': float
        }
    """
    if len(df) < slow:
        return {
            'bullish_aligned': False,
            'bearish_aligned': False,
            'ema_9': None,
            'ema_21': None,
            'ema_50': None
        }
    
    ema_9 = df['close'].ewm(span=fast, adjust=False).mean().iloc[-1]
    ema_21 = df['close'].ewm(span=medium, adjust=False).mean().iloc[-1]
    ema_50 = df['close'].ewm(span=slow, adjust=False).mean().iloc[-1]
    
    bullish_aligned = ema_9 > ema_21 > ema_50
    bearish_aligned = ema_9 < ema_21 < ema_50
    
    return {
        'bullish_aligned': bullish_aligned,
        'bearish_aligned': bearish_aligned,
        'ema_9': ema_9,
        'ema_21': ema_21,
        'ema_50': ema_50
    }


def check_volume_confirmation(df, threshold=1.5):
    """
    Check if current volume meets minimum threshold for valid signals.
    
    Args:
        df: DataFrame with 'volume' column
        threshold: Minimum volume multiplier vs 20-period average
    
    Returns:
        dict: {
            'volume_confirmed': bool,
            'current_volume': float,
            'avg_volume': float,
            'volume_ratio': float
        }
    """
    if len(df) < 20:
        return {
            'volume_confirmed': False,
            'current_volume': 0,
            'avg_volume': 0,
            'volume_ratio': 0
        }
    
    current_volume = df['volume'].iloc[-1]
    avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]
    
    if avg_volume == 0:
        volume_ratio = 0
        volume_confirmed = False
    else:
        volume_ratio = current_volume / avg_volume
        volume_confirmed = volume_ratio >= threshold
    
    return {
        'volume_confirmed': volume_confirmed,
        'current_volume': current_volume,
        'avg_volume': avg_volume,
        'volume_ratio': volume_ratio
    }


def detect_vwap_pullback(df, price_tolerance=0.002):
    """
    Detect VWAP pullback opportunity (price pulls back to VWAP in trending market).
    
    Args:
        df: DataFrame with OHLCV data and 'vwap' column
        price_tolerance: How close to VWAP is considered a pullback (default: 0.2%)
    
    Returns:
        dict: {
            'bullish_pullback': bool (price at/near VWAP in uptrend),
            'bearish_pullback': bool (price at/near VWAP in downtrend),
            'distance_from_vwap': float (percentage)
        }
    """
    if len(df) < 21 or 'vwap' not in df.columns:
        return {
            'bullish_pullback': False,
            'bearish_pullback': False,
            'distance_from_vwap': 0
        }
    
    current_price = df['close'].iloc[-1]
    vwap = df['vwap'].iloc[-1]
    ema_21 = df['close'].ewm(span=21, adjust=False).mean().iloc[-1]
    
    if vwap == 0:
        distance_from_vwap = 0
    else:
        distance_from_vwap = (current_price - vwap) / vwap
    
    # Bullish pullback: price near VWAP in uptrend (EMA21 > VWAP)
    bullish_pullback = (
        abs(distance_from_vwap) <= price_tolerance and
        ema_21 > vwap and
        current_price >= vwap * 0.998  # Price just above or at VWAP
    )
    
    # Bearish pullback: price near VWAP in downtrend (EMA21 < VWAP)
    bearish_pullback = (
        abs(distance_from_vwap) <= price_tolerance and
        ema_21 < vwap and
        current_price <= vwap * 1.002  # Price just below or at VWAP
    )
    
    return {
        'bullish_pullback': bullish_pullback,
        'bearish_pullback': bearish_pullback,
        'distance_from_vwap': distance_from_vwap
    }


def detect_ema21_pullback(df, price_tolerance=0.003):
    """
    Detect EMA21 pullback opportunity (price pulls back to EMA21 in trending market).
    
    Args:
        df: DataFrame with OHLCV data
        price_tolerance: How close to EMA21 is considered a pullback (default: 0.3%)
    
    Returns:
        dict: {
            'bullish_pullback': bool,
            'bearish_pullback': bool,
            'distance_from_ema21': float (percentage)
        }
    """
    if len(df) < 50:
        return {
            'bullish_pullback': False,
            'bearish_pullback': False,
            'distance_from_ema21': 0
        }
    
    current_price = df['close'].iloc[-1]
    ema_9 = df['close'].ewm(span=9, adjust=False).mean().iloc[-1]
    ema_21 = df['close'].ewm(span=21, adjust=False).mean().iloc[-1]
    ema_50 = df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
    
    if ema_21 == 0:
        distance_from_ema21 = 0
    else:
        distance_from_ema21 = (current_price - ema_21) / ema_21
    
    # Bullish pullback: price at EMA21 in uptrend
    bullish_pullback = (
        abs(distance_from_ema21) <= price_tolerance and
        ema_9 > ema_21 > ema_50 and
        current_price >= ema_21 * 0.997  # Price just above or at EMA21
    )
    
    # Bearish pullback: price at EMA21 in downtrend
    bearish_pullback = (
        abs(distance_from_ema21) <= price_tolerance and
        ema_9 < ema_21 < ema_50 and
        current_price <= ema_21 * 1.003  # Price just below or at EMA21
    )
    
    return {
        'bullish_pullback': bullish_pullback,
        'bearish_pullback': bearish_pullback,
        'distance_from_ema21': distance_from_ema21
    }
