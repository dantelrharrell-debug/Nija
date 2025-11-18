import time
import logging

# --- Attempt to import your Coinbase client ---
try:
    from nija_client import CoinbaseClient
    COINBASE_AVAILABLE = True
except Exception as e:
    logging.error(f"⚠️ Coinbase client not available: {e}")
    COINBASE_AVAILABLE = False

# --- Initialize logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# --- Trading configuration ---
LIVE_TRADING = True  # switch to False for dry-run
CHECK_INTERVAL = 10  # seconds between signal checks

# --- Trading signals ---
TRADING_SIGNALS = [
    {"symbol": "BTC-USD", "side": "buy", "size": 0.001},
    {"symbol": "BTC-USD", "side": "sell", "size": 0.001},
    {"symbol": "ETH-USD", "side": "buy", "size": 0.01},
    {"symbol": "ETH-USD", "side": "sell", "size": 0.01},
]

# --- Initialize Coinbase client safely ---
coinbase_client = None
if COINBASE_AVAILABLE:
    try:
        coinbase_client = CoinbaseClient(
            api_key="YOUR_API_KEY",
            api_secret_path="/opt/railway/secrets/coinbase.pem",
            api_passphrase="",  # usually empty for Advanced API
            api_sub="YOUR_ACCOUNT_SUB_ID",
        )
        logging.info("✅ Coinbase client initialized successfully")
    except FileNotFoundError:
        logging.error("❌ PEM file not found! Running in dry-run mode.")
        LIVE_TRADING = False
    except Exception as e:
        logging.error(f"❌ Failed to initialize Coinbase client: {e}")
        LIVE_TRADING = False
else:
    logging.warning("⚠️ Coinbase client unavailable. Running in dry-run mode.")
    LIVE_TRADING = False

# --- Functions ---
def check_signals():
    """Return current trading signals"""
    return TRADING_SIGNALS

def place_order(symbol: str, side: str, size: float):
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
    logging.info("🚀 Starting trading loop...")
    while True:
        signals = check_signals()
        if not signals:
            logging.info("⏸ No signals found. Waiting...")
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
