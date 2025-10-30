# trading_logic.py

def generate_signal(symbol, client=None):
    """
    Generates a trading signal for a given symbol.
    Accepts an optional client for live data fetching.
    """
    # --- Fetch historical data ---
    if client:
        # Use live client to fetch historical prices
        try:
            df = client.get_historical_data(symbol)
        except Exception as e:
            print(f"[generate_signal] Error fetching live data for {symbol}: {e}")
            df = fetch_dummy_data(symbol)  # fallback dummy data
    else:
        # No client provided: use dummy/test data
        df = fetch_dummy_data(symbol)

    # --- Simple example signal logic ---
    latest_close = df['close'].iloc[-1]
    avg_close = df['close'].mean()

    if latest_close > avg_close:
        return "buy"
    elif latest_close < avg_close:
        return "sell"
    else:
        return "hold"


def fetch_dummy_data(symbol):
    """
    Returns dummy price data in DataFrame format for testing.
    """
    import pandas as pd
    import numpy as np

    np.random.seed(42)
    prices = np.random.normal(loc=100, scale=5, size=50)  # 50 dummy candles
    df = pd.DataFrame(prices, columns=['close'])
    return df
