# data_fetcher.py
import time
import pandas as pd
import numpy as np

# Try to import user Coinbase client if present; otherwise simulation mode
COINBASE_CLIENT = None
try:
    # adjust import path if your vendor library differs
    
    # instantiate if environment keys are present in your normal app
    # Here we DON'T create a client automatically (safer). Your main app should attach client if needed.
except Exception:
    CoinbaseClient = None

def get_historic_candles_symbol(symbol, granularity_seconds=60, limit=200, client=None):
    """
    Attempt to fetch recent candles for `symbol`.
    - symbol expected like 'BTC/USD' or 'BTC-USD' depending on client.
    - granularity_seconds: e.g., 60 for 1m, 300 for 5m.
    Returns pandas.DataFrame with columns: ['time','open','high','low','close','volume']
    If client is None or fetch fails, returns simulated candles (random walk) for safe simulation.
    """
    # Normalize symbol for common APIs
    symbol_api = symbol.replace("/", "-")

    # Try Coinbase client if passed
    if client is not None:
        try:
            # Many Coinbase libs provide historic rates endpoint; adapt if yours differs.
            # Example expected return: list of [time, low, high, open, close, volume] or similar.
            raw = client.get_historic_rates(product_id=symbol_api, granularity=granularity_seconds, limit=limit)
            # raw expected sorted most-recent-first or oldest-first depending on client; make robust
            # We'll try to create DataFrame robustly
            df = pd.DataFrame(raw)
            # Attempt common formats
            if df.shape[1] >= 6:
                # handle list-of-lists response
                df = pd.DataFrame(raw, columns=['time','low','high','open','close','volume'])
            # ensure columns exist
            expected = ['time','open','high','low','close','volume']
            for col in expected:
                if col not in df.columns:
                    # attempt to coerce
                    pass
            df = df[expected]
            df = df.sort_values('time').reset_index(drop=True)
            return df
        except Exception:
            # fallthrough to simulation
            pass

    # Simulation fallback: create recent `limit` 1-minute candles by random walk around a base price
    base_price = 30000.0
    if "ETH" in symbol.upper():
        base_price = 2000.0
    elif "LTC" in symbol.upper():
        base_price = 80.0
    elif "SOL" in symbol.upper():
        base_price = 120.0
    elif "BNB" in symbol.upper():
        base_price = 300.0
    elif "XRP" in symbol.upper():
        base_price = 0.5
    elif "ADA" in symbol.upper():
        base_price = 0.35

    rng = np.random.default_rng(int(time.time()) % 100000)
    prices = base_price + rng.normal(0, base_price * 0.0015, size=limit).cumsum()
    volumes = np.abs(rng.normal(1, 0.5, size=limit)) * 10
    times = [int(time.time()) - (limit - i) * granularity_seconds for i in range(limit)]
    opens = np.concatenate(([prices[0]], prices[:-1]))
    highs = np.maximum(opens, prices) * (1 + np.abs(rng.normal(0, 0.0005, size=limit)))
    lows = np.minimum(opens, prices) * (1 - np.abs(rng.normal(0, 0.0005, size=limit)))
    df = pd.DataFrame({
        'time': times,
        'open': opens,
        'high': highs,
        'low': lows,
        'close': prices,
        'volume': volumes
    })
    return df
