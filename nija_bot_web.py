# indicators.py
import numpy as np
import pandas as pd

def compute_vwap(df):
    """
    df must have columns: ['close','high','low','volume'] or at least ['close','volume'].
    Returns series with VWAP for each row (cumulative typical price * volume / cumulative volume).
    """
    # typical price: (high + low + close)/3 if high/low present, else close
    if {'high','low'}.issubset(df.columns):
        tp = (df['high'] + df['low'] + df['close']) / 3.0
    else:
        tp = df['close']
    pv = tp * df['volume']
    cum_pv = pv.cumsum()
    cum_vol = df['volume'].cumsum().replace(0, np.nan)
    vwap = cum_pv / cum_vol
    return vwap.fillna(method='ffill').fillna(df['close'])

def compute_rsi(series, period=14):
    """
    Classic RSI (Wilder's smoothing) implementation.
    series must be a pandas Series of close prices.
    Returns pandas Series of RSI values (0-100).
    """
    delta = series.diff()
    up = delta.clip(lower=0.0)
    down = -1 * delta.clip(upper=0.0)

    # first SMA
    roll_up = up.rolling(window=period, min_periods=period).mean()
    roll_down = down.rolling(window=period, min_periods=period).mean()

    # use Wilder smoothing after initial avg
    # initialize avg_gain & avg_loss as first SMA
    avg_gain = roll_up.copy()
    avg_loss = roll_down.copy()
    # apply smoothing
    for i in range(period, len(series)):
        if i == period:
            # already set by rolling mean
            continue
        avg_gain.iat[i] = (avg_gain.iat[i-1] * (period - 1) + up.iat[i]) / period
        avg_loss.iat[i] = (avg_loss.iat[i-1] * (period - 1) + down.iat[i]) / period

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(50)  # neutral where undefined
    return rsi
