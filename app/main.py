import os
import time
import logging
from nija_client import CoinbaseClient  # make sure this matches your actual client file

# -------------------------------
# --- Initialize Coinbase Client
# -------------------------------
coinbase_client = CoinbaseClient(
    api_key=os.getenv("COINBASE_API_KEY"),
    api_secret_path=os.getenv("COINBASE_API_SECRET_PATH"),
    pem_path=os.getenv("COINBASE_PEM_PATH"),
    org_id=os.getenv("COINBASE_ORG_ID"),
    kid=os.getenv("COINBASE_API_KID")
)

# -------------------------------
# --- Trading Config
# -------------------------------
LIVE_TRADING = os.getenv("LIVE_TRADING", "1") == "1"
CHECK_INTERVAL = 10  # seconds between signal checks

# -------------------------------
# --- Signal Function (customize)
# -------------------------------
def check_signals():
    """
    Replace this with your actual signal logic.
    Return a list of signals like:
    [
        {"symbol": "BTC-USD", "side": "buy", "size": 0.001},
        {"symbol": "ETH-USD", "side": "sell", "size": 0.01}
    ]
    """
    # TODO: Implement your signal generation
    return []

# -------------------------------
# --- Place order
# -------------------------------
def place_order(symbol: str, side: str, size: float):
    """
    Executes a market order on Coinbase.
    """
    if not LIVE_TRADING:
        logging.info(f"Dry run: would place {side} order for {size} {symbol}")
        return None

    try:
        order = coinbase_client.create_order(
            product_id=symbol,
            side=side,
            type="market",
            size=str(size)  # Coinbase API requires string
        )
        logging.info(f"✅ Order executed: {order}")
        return order
    except Exception as e:
        logging.error(f"❌ Failed to place order for {symbol} ({side} {size}): {e}")
        return None

# -------------------------------
# --- Trading Loop
# -------------------------------
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

# -------------------------------
# --- Main
# -------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    logging.info("✅ Coinbase client initialized and ready.")
    trading_loop()
