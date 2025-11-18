import time
import logging
from nija_client import CoinbaseClient
from flask import Flask, request, jsonify

# --- Initialize logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# --- Trading configuration ---
LIVE_TRADING = True           # Set False for dry-run
CHECK_INTERVAL = 5            # Poll interval for queued signals

# --- Initialize Coinbase client ---
try:
    coinbase_client = CoinbaseClient(
        api_key="d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5",
        api_secret_path="/opt/railway/secrets/coinbase.pem",
        api_passphrase="",  
        api_sub="organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/9e33d60c-c9d7-4318-a2d5-24e1e53d2206"
    )
    logging.info("✅ Coinbase client ready for live trading")
except Exception as e:
    logging.error(f"❌ Failed to initialize Coinbase client: {e}")
    LIVE_TRADING = False
    coinbase_client = None

# --- Flask app for TradingView alerts ---
app = Flask(__name__)

# Queue for incoming signals
signal_queue = []

@app.route("/alert", methods=["POST"])
def receive_alert():
    data = request.json
    symbol = data.get("symbol")
    side = data.get("side")
    size = data.get("size")
    if symbol and side and size:
        signal_queue.append({"symbol": symbol, "side": side, "size": size})
        logging.info(f"📥 Received alert: {side} {size} {symbol}")
        return jsonify({"status": "ok"}), 200
    else:
        logging.warning(f"⚠️ Invalid alert received: {data}")
        return jsonify({"status": "error", "reason": "Invalid alert"}), 400

# --- Functions ---
def place_order(symbol: str, side: str, size: float):
    """Place a live order if possible; else log dry-run."""
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
    """Continuously execute queued signals."""
    logging.info("🚀 Starting trading loop...")
    while True:
        while signal_queue:
            signal = signal_queue.pop(0)
            place_order(signal["symbol"], signal["side"], signal["size"])
        time.sleep(CHECK_INTERVAL)

# --- Run Flask and trading loop concurrently ---
if __name__ == "__main__":
    from threading import Thread
    t = Thread(target=trading_loop, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000)
