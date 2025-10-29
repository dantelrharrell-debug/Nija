# nija_live_snapshot.py
import time
import logging
from flask import Flask, jsonify
from threading import Thread
from nija_client import client, get_accounts, place_order

# ===== Logging =====
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== Flask App for Health Check =====
app = Flask(__name__)
running = False  # Tracks trading loop

@app.route("/health", methods=["GET"])
def health_check():
    """
    Health endpoint for Render or manual checks.
    Returns:
    - status: Flask alive
    - trading: whether bot loop is running
    - coinbase: whether Coinbase API is reachable
    """
    try:
        accounts = get_accounts()
        coinbase_status = "connected" if accounts else "no accounts"
    except Exception:
        coinbase_status = "error"

    return jsonify({
        "status": "alive",
        "trading": "running" if running else "stopped",
        "coinbase": coinbase_status
    })

# ===== Trading Loop =====
def trading_loop():
    global running
    running = True
    logger.info("Trading loop started")
    
    try:
        while True:
            accounts = get_accounts()
            if not accounts:
                logger.warning("No accounts available, skipping trade cycle")
                time.sleep(10)
                continue

            # Example: trade BTC-USD with 0.001 BTC per cycle (sandbox safe)
            symbol = "BTC-USD"
            side = "buy"
            size = 0.001

            logger.info(f"Placing order: {side} {size} {symbol}")
            order = place_order(symbol=symbol, side=side, size=size)
            
            if order:
                logger.info(f"Order executed: {order}")
            else:
                logger.error("Order failed")

            # Wait 30 seconds before next trade cycle
            time.sleep(30)
    except Exception as e:
        logger.error(f"Trading loop error: {e}")
    finally:
        running = False
        logger.info("Trading loop stopped")

# ===== Start Trading Thread =====
def start_trading():
    thread = Thread(target=trading_loop, daemon=True)
    thread.start()

# ===== Main Entrypoint =====
if __name__ == "__main__":
    logger.info("Starting Nija bot main...")
    start_trading()
    
    # Start Flask server for Render
    app.run(host="0.0.0.0", port=10000)
