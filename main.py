import time
import logging
from nija_client import CoinbaseClient  # Your stable working client
import requests  # Optional: if fetching signals from an API

# --- Initialize Coinbase client (LIVE) ---
coinbase_client = CoinbaseClient(
    api_key="d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5",
    api_secret_path="/opt/railway/secrets/coinbase.pem",
    api_passphrase="",  # usually empty for Advanced API
    api_sub="organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/9e33d60c-c9d7-4318-a2d5-24e1e53d2206",
)

# --- Trading configuration ---
LIVE_TRADING = True
CHECK_INTERVAL = 10  # seconds between signal checks

# --- Default signals ---
TRADING_SIGNALS = [
    {"symbol": "BTC-USD", "side": "buy", "size": 0.001},
    {"symbol": "BTC-USD", "side": "sell", "size": 0.001},
    {"symbol": "ETH-USD", "side": "buy", "size": 0.01},
    {"symbol": "ETH-USD", "side": "sell", "size": 0.01},
]

def fetch_dynamic_signals():
    """
    Fetch dynamic signals from an API or external source.
    Replace this with your TradingView webhook, file, or API.
    If unavailable, return default signals.
    """
    try:
        # Example placeholder: replace with your real endpoint
        # response = requests.get("https://your-signal-provider.com/signals")
        # signals = response.json()
        signals = TRADING_SIGNALS  # fallback to default if dynamic fetch fails
        return signals
    except Exception as e:
        logging.error(f"❌ Failed to fetch dynamic signals: {e}")
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
    logging.info("🚀 Starting live trading loop...")
    while True:
        signals = fetch_dynamic_signals()
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
