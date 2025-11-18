# main.py
import time
import logging
from nija_client import CoinbaseClient

# --- Initialize Coinbase client ---
coinbase_client = CoinbaseClient(
    api_key="d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5",
    api_secret_path="/opt/railway/secrets/coinbase.pem",
    api_passphrase="",
    api_sub="organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/9e33d60c-c9d7-4318-a2d5-24e1e53d2206",
)

LIVE_TRADING = True
CHECK_INTERVAL = 10  # seconds
MIN_RISK = 0.02  # 2% of equity
MAX_RISK = 0.10  # 10% of equity

# --- Dynamic order size calculation ---
def calculate_order_size(symbol):
    usd_balance = coinbase_client.get_account_balance("USD")
    price = coinbase_client.get_ticker_price(symbol)
    
    if price <= 0 or usd_balance <= 0:
        logging.warning(f"Cannot calculate size for {symbol} (price={price}, balance={usd_balance})")
        return 0
    
    # Base 5% risk
    size = (usd_balance * 0.05) / price

    # Enforce min/max
    fraction = size * price / usd_balance
    if fraction < MIN_RISK:
        size = (MIN_RISK * usd_balance) / price
    elif fraction > MAX_RISK:
        size = (MAX_RISK * usd_balance) / price

    return round(size, 8)

# --- Signals ---
def check_signals():
    """
    Generates signals with dynamic sizing.
    """
    return [
        {"symbol": "BTC-USD", "side": "buy", "size": calculate_order_size("BTC-USD")},
        {"symbol": "BTC-USD", "side": "sell", "size": calculate_order_size("BTC-USD")},
        {"symbol": "ETH-USD", "side": "buy", "size": calculate_order_size("ETH-USD")},
        {"symbol": "ETH-USD", "side": "sell", "size": calculate_order_size("ETH-USD")},
    ]

# --- Place order ---
def place_order(symbol, side, size):
    if size <= 0:
        logging.warning(f"Skipping {side} {symbol} due to zero size")
        return None

    if not LIVE_TRADING:
        logging.info(f"Dry run: {side} {size} {symbol}")
        return None

    order = coinbase_client.create_order(symbol, side, size=size)
    if order:
        logging.info(f"✅ Order executed: {order}")
    return order

# --- Trading loop ---
def trading_loop():
    logging.info("🚀 Starting trading loop...")
    while True:
        signals = check_signals()
        for sig in signals:
            place_order(sig["symbol"], sig["side"], sig["size"])
        time.sleep(CHECK_INTERVAL)

# --- Entry point ---
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    trading_loop()
