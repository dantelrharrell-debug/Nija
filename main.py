import time
import logging

# Use your existing Coinbase client from the stable rollback
# Make sure this is already initialized somewhere in your working code
# Example from your rollback:
# from nija_client import CoinbaseClient
# coinbase_client = CoinbaseClient(...)

LIVE_TRADING = True  # Already set in your env
CHECK_INTERVAL = 10  # seconds between signal checks

# Your trading signals
TRADING_SIGNALS = [
    {"symbol": "BTC-USD", "side": "buy", "size": 0.001},
    {"symbol": "BTC-USD", "side": "sell", "size": 0.001},
    {"symbol": "ETH-USD", "side": "buy", "size": 0.01},
    {"symbol": "ETH-USD", "side": "sell", "size": 0.01},
    # Add all other pairs you want to trade here
]

def check_signals():
    """
    Returns the current trading signals.
    Replace this logic if you want dynamic signals.
    """
    return TRADING_SIGNALS

def place_order(symbol: str, side: str, size: float):
    """
    Executes a market order on Coinbase using your stable client.
    """
    if not LIVE_TRADING:
        logging.info(f"Dry run: would place {side} order for {size} {symbol}")
        return None

    try:
        order = coinbase_client.create_order(
            product_id=symbol,
            side=side,
            type="market",
            size=str(size)  # Coinbase API requires strings
        )
        logging.info(f"✅ Order executed: {order}")
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
                place_order(symbol, side, size)
            else:
                logging.warning(f"Incomplete signal skipped: {signal}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    trading_loop()
