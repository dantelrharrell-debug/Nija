import time
import logging
from nija_client import CoinbaseClient  # your stable, working client

# --- Initialize Coinbase client (LIVE) ---
coinbase_client = CoinbaseClient(
    api_key="YOUR_REAL_API_KEY",
    api_secret_path="/opt/railway/secrets/coinbase.pem",
    api_passphrase="",  
    api_sub="YOUR_REAL_ACCOUNT_SUB_ID",
)

# --- Trading configuration ---
LIVE_TRADING = True
CHECK_INTERVAL = 10  # seconds

# --- Trading signals ---
TRADING_SIGNALS = [
    {"symbol": "BTC-USD", "side": "buy", "size": 0.001},
    {"symbol": "BTC-USD", "side": "sell", "size": 0.001},
    {"symbol": "ETH-USD", "side": "buy", "size": 0.01},
    {"symbol": "ETH-USD", "side": "sell", "size": 0.01},
]

def check_signals():
    return TRADING_SIGNALS

def place_order(symbol: str, side: str, size: float):
    try:
        order = coinbase_client.create_order(
            product_id=symbol,
            side=side,
            type="market",
            size=str(size)
        )
        logging.info(f"✅ Order executed: {side} {size} {symbol} | ID: {order.get('id')}")
        return order
    except Exception as e:
        logging.error(f"❌ Failed to place order {side} {size} {symbol}: {e}")
        return None

def trading_loop():
    logging.info("🚀 Starting fully live trading loop...")
    while True:
        signals = check_signals()
        for signal in signals:
            symbol = signal.get("symbol")
            side = signal.get("side")
            size = signal.get("size")
            if symbol and side and size:
                place_order(symbol, side, size)
            else:
                logging.warning(f"⚠️ Incomplete signal skipped: {signal}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    trading_loop()
