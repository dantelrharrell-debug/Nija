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
CHECK_INTERVAL = 10  # seconds between signal checks

# --- Define your trading signals ---
TRADING_SIGNALS = [
    {"symbol": "BTC-USD", "side": "buy", "size": 0.001},
    {"symbol": "BTC-USD", "side": "sell", "size": 0.001},
    {"symbol": "ETH-USD", "side": "buy", "size": 0.01},
    {"symbol": "ETH-USD", "side": "sell", "size": 0.01},
    # Add any other pairs you want to trade here
]

def check_signals():
    """Return the current trading signals."""
    return TRADING_SIGNALS

def place_order(symbol: str, side: str, size: float):
    """Execute a market order on Coinbase."""
    if not LIVE_TRADING:
        logging.info(f"Dry run: would place {side} order for {size} {symbol}")
        return None

    try:
        order = coinbase_client.create_order(
            product_id=symbol,
            side=side,
            type="market",
            size=str(size)
        )
        return order
    except Exception as e:
        logging.error(f"❌ Failed to place order for {symbol} ({side} {size}): {e}")
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
                order = place_order(symbol, side, size)
                if order:
                    logging.info(f"✅ Order placed successfully: {order}")
            else:
                logging.warning(f"Incomplete signal skipped: {signal}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    trading_loop()
