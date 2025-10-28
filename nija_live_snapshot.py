#!/usr/bin/env python3
# nija_live_snapshot.py
import os
import time
import logging
from flask import Flask, jsonify
from coinbase_advanced_py.client import CoinbaseClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NijaBot")

# Initialize Coinbase client using environment variables
try:
    client = CoinbaseClient(
        api_key=os.environ["COINBASE_API_KEY"],
        api_secret=os.environ["COINBASE_API_SECRET"],
        api_passphrase=os.environ.get("COINBASE_PASSPHRASE")  # optional
    )
    logger.info("✅ Coinbase client initialized successfully.")
except KeyError as e:
    logger.error(f"Missing Coinbase environment variable: {e}")
    raise
except Exception as e:
    logger.error(f"Failed to initialize Coinbase client: {e}")
    raise

# Flask app for health check
app = Flask(__name__)
running = False

@app.route("/health", methods=["GET"])
def health_check():
    """
    Returns JSON with:
    - status: Flask alive
    - trading: whether bot loop is running
    - coinbase: whether Coinbase API is reachable
    """
    global running
    trading_status = "live" if running else "stopped"

    try:
        accounts = client.get_accounts()
        coinbase_status = "reachable" if accounts else "unreachable"
    except Exception as e:
        coinbase_status = f"error: {e}"

    return jsonify({
        "status": "Flask alive",
        "trading": trading_status,
        "coinbase": coinbase_status
    })

# Main trading loop (simplified)
def trading_loop():
    global running
    running = True
    logger.info("🚀 Nija bot trading loop started.")
    try:
        while True:
            # Example: fetch accounts
            accounts = client.get_accounts()
            logger.info(f"Accounts fetched: {len(accounts)}")
            # TODO: add your live trading logic here
            time.sleep(10)  # adjust frequency as needed
    except KeyboardInterrupt:
        logger.info("⚠️ Trading loop interrupted.")
    except Exception as e:
        logger.error(f"Error in trading loop: {e}")
    finally:
        running = False
        logger.info("⏹️ Trading loop stopped.")

if __name__ == "__main__":
    from threading import Thread
    # Start trading in a separate thread
    t = Thread(target=trading_loop)
    t.start()
    # Run Flask for health checks
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
