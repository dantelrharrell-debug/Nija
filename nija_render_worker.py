# nija_render_worker.py
import os
import logging
from flask import Flask, jsonify
from nija_client import client  # This will be live CoinbaseClient if keys exist

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_worker")

# --- Flask app for Render health checks and WSGI compatibility ---
app = Flask(__name__)

@app.route("/")
def index():
    status = "LIVE ✅" if type(client).__name__ != "DummyClient" else "SIMULATED ⚠️"
    return jsonify({"status": status})

@app.route("/place_test_order")
def place_test_order():
    """
    Optional test endpoint to place a small order
    """
    try:
        order = client.place_order(
            product_id="BTC-USD",
            side="buy",
            type="market",
            funds="10"  # $10 USD buy for testing
        )
        return jsonify({"order": order, "status": "SUCCESS"})
    except Exception as e:
        logger.error(f"Failed to place test order: {e}")
        return jsonify({"status": "ERROR", "error": str(e)}), 500

# --- Bot loop (optional: for live trading) ---
def run_bot():
    import time
    while True:
        try:
            # Example trading logic placeholder
            # Replace with your actual strategy
            logger.info("Bot heartbeat: running trading cycle...")
            # Example: client.place_order(...) 
        except Exception as e:
            logger.error(f"Bot error: {e}")
        time.sleep(60)  # run every 60s

# --- Start Flask app for Render ---
def run_worker(environ=None, start_response=None):
    """WSGI-compatible entrypoint for Gunicorn"""
    return app(environ, start_response)

if __name__ == "__main__":
    # For direct local run (outside Gunicorn)
    logger.info("Starting Nija worker locally...")
    # Optional: start bot loop in a separate thread if needed
    # import threading
    # threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
