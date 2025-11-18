import time
import logging
from nija_client import CoinbaseClient

# Initialize Coinbase client
coinbase_client = CoinbaseClient(
    api_key="YOUR_API_KEY",
    api_secret_path="/opt/railway/secrets/coinbase.pem",
    api_passphrase="",
    api_sub="YOUR_ACCOUNT_ID"
)

LIVE_TRADING = True
CHECK_INTERVAL = 10

TRADING_SIGNALS = [
    {"symbol": "BTC-USD", "side": "buy", "size": 0.001},
    {"symbol": "BTC-USD", "side": "sell", "size": 0.001},
    {"symbol": "ETH-USD", "side": "buy", "size": 0.01},
    {"symbol": "ETH-USD", "side": "sell", "size": 0.01},
]

def check_signals():
    return TRADING_SIGNALS

def place_order(symbol, side, size):
    if not LIVE_TRADING:
        logging.info(f"Dry run: {side} {size} {symbol}")
        return None
    try:
        order = coinbase_client.create_order(
            product_id=symbol,
            side=side,
            type="market",
            size=str(size)
        )
        logging.info(f"✅ Order executed: {order}")
        return order
    except Exception as e:
        logging.error(f"❌ Failed to place order {side} {size} {symbol}: {e}")
        return None

def trading_loop():
    logging.info("🚀 Starting trading loop...")
    while True:
        for signal in check_signals():
            place_order(signal["symbol"], signal["side"], signal["size"])
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    trading_loop()
