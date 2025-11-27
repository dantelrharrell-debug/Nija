import os
import time
import logging
import pandas as pd
import requests
from coinbase_advanced.client import Client

# ----------------------
# CONFIG
# ----------------------
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")
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
# LOGGING
# ----------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# ----------------------
# CLIENT INIT
# ----------------------
client = Client(api_key=API_KEY, api_secret=API_SECRET)

# ----------------------
# POSITION STATE
# ----------------------
active_position = {
    "side": None,          # "buy" or "sell"
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
    df = df.sort_values("time").tail(100)  # keep last 100 candles
    cached_df = df
    logging.info("Initialized candle cache with last 100 candles")

def update_candle_cache():
    """Update only the latest candle from API"""
    global cached_df
    last_time = int(cached_df['time'].iloc[-1])
    url = f"https://api.exchange.coinbase.com/products/{PRODUCT_ID}/candles?granularity=60&start={last_time}"
    resp = requests.get(url)
    data = resp.json()
    if data:
        df_new = pd.DataFrame(data, columns=["time", "low", "high", "open", "close", "volume"])
        df_new = df_new.sort_values("time")
        df_new = df_new[df_new['time'] > last_time]  # avoid duplicate
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
        # Stop loss
        if latest_price <= entry * (1 - STOP_LOSS_PCT):
            logging.info(f"BUY stop loss triggered at {latest_price}")
            return True
        # Trailing stop
        if ts and latest_price <= ts:
            logging.info(f"BUY trailing stop triggered at {latest_price}")
            return True
        # Take profit
        if latest_price >= entry * (1 + TAKE_PROFIT_PCT):
            logging.info(f"BUY take profit triggered at {latest_price}")
            return True
        # Trailing take profit
        if tp:
            active_position['trailing_tp'] = max(tp, latest_price * (1 - TRAILING_TAKE_PROFIT_PCT))
            if latest_price <= active_position['trailing_tp']:
                logging.info(f"BUY trailing take profit triggered at {latest_price}")
                return True

    elif side == "sell":
        # Stop loss
        if latest_price >= entry * (1 + STOP_LOSS_PCT):
            logging.info(f"SELL stop loss triggered at {latest_price}")
            return True
        # Trailing stop
        if ts and latest_price >= ts:
            logging.info(f"SELL trailing stop triggered at {latest_price}")
            return True
        # Take profit
        if latest_price <= entry * (1 - TAKE_PROFIT_PCT):
            logging.info(f"SELL take profit triggered at {latest_price}")
            return True
        # Trailing take profit
        if tp:
            active_position['trailing_tp'] = min(tp, latest_price * (1 + TRAILING_TAKE_PROFIT_PCT))
            if latest_price >= active_position['trailing_tp']:
                logging.info(f"SELL trailing take profit triggered at {latest_price}")
                return True
    return False

def execute_trade():
    global active_position
    ticker = client.get_product_ticker(PRODUCT_ID)
    price = float(ticker['price'])
    update_candle_cache()  # update latest candle
    signal = get_trade_signal(price)

    # Exit current position if needed
    if check_exit_conditions(price):
        logging.info(f"Exiting {active_position['side']} position at {price}")
        # Replace with actual API call
        client.place_market_order(PRODUCT_ID, "sell" if active_position['side']=="buy" else "buy", active_position['size'])
        active_position = {"side": None, "entry_price": None, "size": None, "trailing_stop": None, "trailing_tp": None}
        return

    # Enter new position
    if active_position['side'] is None and signal:
        size = calculate_order_size()
        logging.info(f"Opening {signal} position of size {size} at {price}")
        # Replace with actual API call
        client.place_market_order(PRODUCT_ID, signal, size)
        # Initialize position state
        active_position['side'] = signal
        active_position['entry_price'] = price
        active_position['size'] = size
        # Initialize trailing stop/take profit
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
    logging.info("Nija Trading Bot Starting with full strategy...")
    init_candle_cache()
    while True:
        try:
            execute_trade()
        except Exception as e:
            logging.error(f"Error in trading loop: {e}")
        time.sleep(TRADE_INTERVAL)
