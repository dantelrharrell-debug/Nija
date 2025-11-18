import time
import logging
from nija_client import CoinbaseClient  # Your stable working Coinbase client

# --- Initialize logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# --- Live trading configuration ---
LIVE_TRADING = True  # True = execute real trades
CHECK_INTERVAL = 10  # seconds between signal checks

# --- Trading signals ---
TRADING_SIGNALS = [
    {"symbol": "BTC-USD", "side": "buy", "size": 0.001},
    {"symbol": "BTC-USD", "side": "sell", "size": 0.001},
    {"symbol": "ETH-USD", "side": "buy", "size": 0.01},
    {"symbol": "ETH-USD", "side": "sell", "size": 0.01},
]

# --- Initialize Coinbase client ---
try:
    coinbase_client = CoinbaseClient(
        api_key="d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5",  # Your real API key
        api_secret_path="/opt/railway/secrets/coinbase.pem",
        api_passphrase="",  # usually empty for Advanced API
        api_sub="organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/9e33d60c-c9d7-4318-a2d5-24e1e53d2206",  # Your account sub
    )
    logging.info("✅ Coinbase client initialized successfully")
except FileNotFoundError:
    logging.error("❌ PEM file not found! Cannot go live.")
    LIVE_TRADING = False
except Exception as e:
    logging.error(f"❌ Failed to initialize Coinbase client: {e}")
    LIVE_TRADING = False

# --- Functions ---
def check_signals():
    """Return current trading signals"""
    return TRADING_SIGNALS

def place_order(symbol: str, side: str, size: float):
    """Place a market order via Coinbase Advanced API"""
    if not LIVE_TRADING or coinbase_client is None:
        logging.info(f"💡 Dry-run: {side} {size} {symbol}")
        return None
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
    logging.info("🚀 Starting live trading loop...")
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

# --- Main entry ---
if __name__ == "__main__":
    trading_loop()
