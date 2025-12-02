import os
import logging
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# -----------------------------
# Logging setup
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# -----------------------------
# Coinbase credentials
# -----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

# -----------------------------
# Initialize Coinbase client
# -----------------------------
client = None
if API_KEY and API_SECRET:
    try:
        from coinbase_advanced_py.client import Client
        client = Client(api_key=API_KEY, api_secret=API_SECRET)
        logger.info("Coinbase client initialized. Live trading enabled.")
    except Exception as e:
        logger.error(f"Failed to initialize Coinbase client: {e}")
else:
    logger.warning("Coinbase client not initialized. Missing API_KEY or API_SECRET. Live trading disabled.")

# -----------------------------
# Helper functions
# -----------------------------

def get_account_balance(currency="USD"):
    """Fetch account balance for a specific currency."""
    accounts = client.get_accounts()
    for account in accounts:
        if account["currency"] == currency:
            return float(account["balance"])
    return 0.0

def get_recent_candles(symbol="BTC-USD", granularity=60):
    """
    Fetch recent candle data.
    Returns a DataFrame with columns: time, open, high, low, close, volume
    """
    candles = client.get_candles(product_id=symbol, granularity=granularity)
    df = pd.DataFrame(candles)
    df['time'] = pd.to_datetime(df['time'])
    df = df.sort_values('time')
    return df

def compute_vwap(df):
    """Compute VWAP over the DataFrame."""
    q = df['volume']
    p = df['close']
    vwap = (p * q).cumsum() / q.cumsum()
    df['vwap'] = vwap
    return df

def compute_rsi(df, period=14):
    """Compute RSI for the close prices."""
    delta = df['close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

def calculate_position_size(account_balance, risk_percent=5, price=0, min_percent=2, max_percent=10):
    """
    Calculate position size based on account equity and desired risk %.
    """
    risk_percent = np.clip(risk_percent, min_percent, max_percent)
    size_usd = account_balance * (risk_percent / 100)
    size_units = size_usd / price if price > 0 else 0
    return round(size_units, 6)

def place_order(symbol, side, size, order_type="market"):
    """Place a live market order."""
    try:
        order = client.place_order(
            product_id=symbol,
            side=side,
            size=size,
            type=order_type
        )
        logger.info(f"Order placed: {side.upper()} {size} {symbol}")
        return order
    except Exception as e:
        logger.error(f"Failed to place order: {e}")
        return None

# -----------------------------
# Trading logic
# -----------------------------
def trading_logic(symbol="BTC-USD"):
    account_balance = get_account_balance("USD")
    df = get_recent_candles(symbol, granularity=60)
    df = compute_vwap(df)
    df = compute_rsi(df)

    latest = df.iloc[-1]
    price = latest['close']
    vwap = latest['vwap']
    rsi = latest['rsi']

    logger.info(f"{symbol} | Price: {price:.2f} | VWAP: {vwap:.2f} | RSI: {rsi:.2f} | Balance: {account_balance:.2f}")

    # Simple live strategy example
    # Buy signal: price crosses above VWAP and RSI < 70
    if price > vwap and rsi < 70:
        size = calculate_position_size(account_balance, risk_percent=5, price=price)
        if size > 0:
            place_order(symbol, side="buy", size=size)

    # Sell signal: price below VWAP or RSI > 70
    elif price < vwap or rsi > 70:
        # In live trading, you should calculate your current BTC position
        btc_balance = get_account_balance("BTC")
        if btc_balance > 0:
            place_order(symbol, side="sell", size=btc_balance)

# -----------------------------
# Live trading loop
# -----------------------------
def start_live_trading():
    if not client:
        logger.error("Cannot start live trading: Coinbase client not initialized.")
        return

    logger.info("Starting fully live trading loop...")
    try:
        while True:
            trading_logic(symbol="BTC-USD")
            time.sleep(60)  # 1-minute interval
    except KeyboardInterrupt:
        logger.info("Live trading loop stopped by user.")
    except Exception as e:
        logger.error(f"Error in live trading loop: {e}")

# -----------------------------
# Entry point
# -----------------------------
if __name__ == "__main__":
    start_live_trading()
