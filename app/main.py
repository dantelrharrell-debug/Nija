# main.py
import time
import logging
from nija_client import CoinbaseClient

# ---------- Initialize Coinbase client ----------
coinbase_client = CoinbaseClient(
    api_key="d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5",
    api_secret_path="/opt/railway/secrets/coinbase.pem",
    api_passphrase="",
    api_sub="14f3af21-7544-412c-8409-98dc92cd2eec",  # your live account ID
)

LIVE_TRADING = True
CHECK_INTERVAL = 10  # seconds between signal checks

# ---------- All active trading signals ----------
TRADING_SIGNALS = [
    {"symbol": "BTC-USD", "side": "buy", "size": 0.001},
    {"symbol": "BTC-USD", "side": "sell", "size": 0.001},
    {"symbol": "ETH-USD", "side": "buy", "size": 0.01},
    {"symbol": "ETH-USD", "side": "sell", "size": 0.01},
    # Add any additional pairs here
]

# ---------- Check signals ----------
def check_signals():
    return TRADING_SIGNALS

# ---------- Place orders ----------
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

# ---------- Trading loop ----------
def trading_loop():
    logging.info("🚀 Starting live trading loop...")
    while True:
        signals = check_signals()
        if not signals:
            logging.info("No signals found.")
        for signal in signals:
            symbol = signal.get("symbol")
            side = signal.get("side")
            size = signal.get("size")
            if symbol and side and size:
                place_order(symbol, side, size)
            else:
                logging.warning(f"Incomplete signal skipped: {signal}")
        time.sleep(CHECK_INTERVAL)

# ---------- Entry point ----------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    trading_loop()
