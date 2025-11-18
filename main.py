import os
import time
import logging
import traceback
from nija_client import CoinbaseClient  # make sure this exists

# ------------------------------
# Load environment variables
# ------------------------------
LIVE_TRADING = os.getenv("LIVE_TRADING", "0") == "1"
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 10))

COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
COINBASE_KID = os.getenv("COINBASE_KID")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
TRADING_ACCOUNT_ID = os.getenv("TRADING_ACCOUNT_ID")

# ------------------------------
# Initialize Coinbase client
# ------------------------------
coinbase_client = CoinbaseClient(
    pem_path=COINBASE_PEM_PATH,
    kid=COINBASE_KID,
    org_id=COINBASE_ORG_ID,
    sub=f"organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_KID}"
)

# ------------------------------
# Your trading signals
# ------------------------------
TRADING_SIGNALS = [
    {"symbol": "BTC-USD", "side": "buy", "size": 0.001},
    {"symbol": "BTC-USD", "side": "sell", "size": 0.001},
    {"symbol": "ETH-USD", "side": "buy", "size": 0.01},
    {"symbol": "ETH-USD", "side": "sell", "size": 0.01},
    # Add all other pairs you want to trade here
]

# ------------------------------
# Functions
# ------------------------------
def check_signals():
    return TRADING_SIGNALS

def place_order(symbol: str, side: str, size: float):
    if not LIVE_TRADING:
        logging.info(f"Dry run: would place {side} order for {size} {symbol}")
        return None

    try:
        order = coinbase_client.create_order(
            account_id=TRADING_ACCOUNT_ID,
            product_id=symbol,
            side=side,
            type="market",
            size=str(size)
        )
        logging.info(f"✅ Order executed: {order}")
        return order
    except Exception as e:
        logging.error(f"❌ Failed to place order for {symbol} ({side} {size}): {e}")
        logging.error(traceback.format_exc())
        return None

def trading_loop():
    logging.info("🚀 Starting live trading loop...")
    while True:
        signals = check_signals()
        if not signals:
            logging.info("No signals found. Waiting for next check...")
        for signal in signals:
            symbol = signal.get("symbol")
            side = signal.get("side")
            size = signal.get("size")
            if symbol and side and size:
                place_order(symbol, side, size)
            else:
                logging.warning(f"Incomplete signal skipped: {signal}")
        time.sleep(CHECK_INTERVAL)

# ------------------------------
# Main
# ------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    trading_loop()
