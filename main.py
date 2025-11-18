import time
import logging

# ======= LIVE TRADING CONFIG =======
LIVE_TRADING = True
CHECK_INTERVAL = 10  # seconds between signal checks

# Placeholder trading signals
TRADING_SIGNALS = [
    {"symbol": "BTC-USD", "side": "buy", "size": 0.001},
    {"symbol": "BTC-USD", "side": "sell", "size": 0.001},
    {"symbol": "ETH-USD", "side": "buy", "size": 0.01},
    {"symbol": "ETH-USD", "side": "sell", "size": 0.01},
]

# ======= CHECK SIGNALS =======
def check_signals():
    """Return current trading signals."""
    return TRADING_SIGNALS

# ======= PLACE ORDER =======
def place_order(symbol: str, side: str, size: float):
    """
    Safe placeholder for executing orders.
    Once Coinbase library is installed, replace this with coinbase_client.create_order().
    """
    if LIVE_TRADING:
        logging.info(f"🚀 Placing order: {side} {size} {symbol} (placeholder)")
    else:
        logging.info(f"Dry run: {side} {size} {symbol}")

# ======= TRADING LOOP =======
def trading_loop():
    logging.info("🚀 Starting trading loop...")
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

# ======= MAIN =======
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    trading_loop()
