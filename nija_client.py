import os
import time
import logging
from typing import Optional

# ----------------------
# LOGGING
# ----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# ----------------------
# SAFE IMPORTS
# ----------------------
try:
    from coinbase_advanced_py.client import Client  # ✅ Correct import
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced_py module not installed. Install it with `pip install coinbase-advanced-py`.")

try:
    import pandas as pd
except ImportError:
    pd = None
    logging.error("pandas not installed. Install it with `pip install pandas`.")

try:
    import numpy as np
except ImportError:
    np = None
    logging.error("numpy not installed. Install it with `pip install numpy`.")

try:
    import requests
except ImportError:
    requests = None
    logging.error("requests not installed. Install it with `pip install requests`.")

# ----------------------
# COINBASE CLIENT
# ----------------------
def get_coinbase_client() -> Optional[Client]:
    if Client is None:
        logging.error("Coinbase client unavailable. Cannot create client.")
        return None

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")

    if not api_key or not api_secret:
        logging.error("Coinbase API key/secret missing in environment variables.")
        return None

    try:
        client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        return client
    except Exception as e:
        logging.error(f"Failed to initialize Coinbase client: {e}")
        return None

def test_coinbase_connection() -> bool:
    client = get_coinbase_client()
    if client is None:
        return False
    try:
        accounts = client.get_accounts()
        logging.info(f"Coinbase connection successful. Accounts: {len(accounts)}")
        return True
    except Exception as e:
        logging.error(f"Failed to connect to Coinbase: {e}")
        return False

# ----------------------
# TRADING CONFIG
# ----------------------
PRODUCT_ID = "BTC-USD"

STOP_LOSS_PCT = 0.02
TRAILING_STOP_PCT = 0.01
TAKE_PROFIT_PCT = 0.03
TRAILING_TAKE_PROFIT_PCT = 0.01
MIN_POS_PCT = 0.02
MAX_POS_PCT = 0.10
TRADE_INTERVAL = 5

VWAP_PERIOD = 20
RSI_PERIOD = 14

# ----------------------
# POSITION STATE
# ----------------------
active_position = {
    "side": None,
    "entry_price": None,
    "size": None,
    "trailing_stop": None,
    "trailing_tp": None
}

# ----------------------
# MARKET DATA CACHE
# ----------------------
cached_df = None

def init_candle_cache():
    global cached_df
    url = f"https://api.exchange.coinbase.com/products/{PRODUCT_ID}/candles?granularity=60"
    resp = requests.get(url)
    data = resp.json()
    df = pd.DataFrame(data, columns=["time", "low", "high", "open", "close", "volume"])
    df = df.sort_values("time").tail(100)
    cached_df = df
    logging.info("Initialized candle cache with last 100 candles")

def update_candle_cache():
    global cached_df
    last_time = int(cached_df['time'].iloc[-1])
    url = f"https://api.exchange.coinbase.com/products/{PRODUCT_ID}/candles?granularity=60&start={last_time}"
    resp = requests.get(url)
    data = resp.json()
    if data:
        df_new = pd.DataFrame(data, columns=["time", "low", "high", "open", "close", "volume"])
        df_new = df_new.sort_values("time")
        df_new = df_new[df_new['time'] > last_time]
        if not df_new.empty:
            cached_df = pd.concat([cached_df, df_new]).tail(100)

# ----------------------
# INDICATORS
# ----------------------
def compute_vwap(df):
    return (df['close'] * df['volume']).sum() / df['volume'].sum()

def compute_rsi(df, period=14):
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

# ----------------------
# SIGNALS
# ----------------------
def get_trade_signal(latest_price):
    df = cached_df
    vwap = compute_vwap(df)
    rsi = compute_rsi(df, RSI_PERIOD)
    if latest_price > vwap and rsi < 30:
        return "buy"
    elif latest_price < vwap and rsi > 70:
        return "sell"
    else:
        return None

# ----------------------
# POSITION MANAGEMENT
# ----------------------
def calculate_order_size():
    client = get_coinbase_client()
    if client is None:
        return 0.0001
    account = client.get_account(PRODUCT_ID.split("-")[0])
    equity = float(account['balance'])
    size = equity * MIN_POS_PCT
    return max(size, 0.0001)

def check_exit_conditions(latest_price):
    global active_position
    if active_position['side'] is None:
        return False

    side = active_position['side']
    entry = active_position['entry_price']
    ts = active_position['trailing_stop']
    tp = active_position['trailing_tp']

    if side == "buy":
        if latest_price <= entry * (1 - STOP_LOSS_PCT): return True
        if ts and latest_price <= ts: return True
        if latest_price >= entry * (1 + TAKE_PROFIT_PCT): return True
        if tp:
            active_position['trailing_tp'] = max(tp, latest_price * (1 - TRAILING_TAKE_PROFIT_PCT))
            if latest_price <= active_position['trailing_tp']: return True

    elif side == "sell":
        if latest_price >= entry * (1 + STOP_LOSS_PCT): return True
        if ts and latest_price >= ts: return True
        if latest_price <= entry * (1 - TAKE_PROFIT_PCT): return True
        if tp:
            active_position['trailing_tp'] = min(tp, latest_price * (1 + TRAILING_TAKE_PROFIT_PCT))
            if latest_price >= active_position['trailing_tp']: return True

    return False

def execute_trade():
    global active_position
    client = get_coinbase_client()
    if client is None:
        logging.error("Cannot execute trade: Coinbase client unavailable")
        return

    ticker = client.get_product_ticker(PRODUCT_ID)
    price = float(ticker['price'])
    update_candle_cache()
    signal = get_trade_signal(price)

    # Exit position
    if check_exit_conditions(price):
        logging.info(f"Exiting {active_position['side']} position at {price}")
        client.place_market_order(PRODUCT_ID, "sell" if active_position['side']=="buy" else "buy", active_position['size'])
        active_position = {"side": None, "entry_price": None, "size": None, "trailing_stop": None, "trailing_tp": None}
        return

    # Enter position
    if active_position['side'] is None and signal:
        size = calculate_order_size()
        logging.info(f"Opening {signal} position of size {size} at {price}")
        client.place_market_order(PRODUCT_ID, signal, size)
        active_position['side'] = signal
        active_position['entry_price'] = price
        active_position['size'] = size
        if signal == "buy":
            active_position['trailing_stop'] = price * (1 - TRAILING_STOP_PCT)
            active_position['trailing_tp'] = price * (1 - TRAILING_TAKE_PROFIT_PCT)
        else:
            active_position['trailing_stop'] = price * (1 + TRAILING_STOP_PCT)
            active_position['trailing_tp'] = price * (1 + TRAILING_TAKE_PROFIT_PCT)

# ----------------------
# MAIN LOOP
# ----------------------
if __name__ == "__main__":
    logging.info("=== Nija Trading Bot Starting ===")
    if not test_coinbase_connection():
        raise RuntimeError("Coinbase client unavailable. Install coinbase-advanced-py and set API keys.")

    init_candle_cache()

    while True:
        try:
            execute_trade()
        except Exception as e:
            logging.error(f"Error in trading loop: {e}")
        time.sleep(TRADE_INTERVAL)
