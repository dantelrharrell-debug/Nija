# trading_logic.py
import pandas as pd
import numpy as np
from indicators import calculate_vwap, calculate_rsi  # make sure these exist

def generate_signal(df: pd.DataFrame) -> str:
    """
    Generates a trading signal: 'buy', 'sell', or 'hold'.
    Uses VWAP and RSI as simple indicators.
    """
    if df.empty or df.shape[0] < 2:
        return "hold"  # safe default if no data

    # Ensure numeric types
    df[['open','high','low','close','volume']] = df[['open','high','low','close','volume']].apply(pd.to_numeric, errors='coerce').ffill()

    try:
        vwap = calculate_vwap(df)
        rsi = calculate_rsi(df['close'])
    except Exception as e:
        print(f"[trading_logic] Indicator calculation failed: {e}")
        return "hold"

    latest_close = df['close'].iloc[-1]

    # Example simple logic
    if latest_close > vwap.iloc[-1] and rsi.iloc[-1] < 70:
        return "buy"
    elif latest_close < vwap.iloc[-1] and rsi.iloc[-1] > 30:
        return "sell"
    else:
        return "hold"

# Optional: allow direct testing
if __name__ == "__main__":
    # create dummy DataFrame for quick test
    data = {
        "open": [1,2,3],
        "high": [2,3,4],
        "low": [1,2,3],
        "close": [1.5,2.5,3.5],
        "volume": [100,200,150]
    }
    df_test = pd.DataFrame(data)
    signal = generate_signal(df_test)
    print(f"Test signal: {signal}")
