import logging
import threading
import time
from flask import Flask
from nija_client import test_coinbase_connection, start_trading_loop  # Make sure this exists

# ---------------------------
# Logging Setup
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------------------
# Flask App for Health Check
# ---------------------------
app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

# ---------------------------
# Startup Tasks
# ---------------------------
@app.before_first_request
def startup_tasks():
    logger.info("Starting bot tasks...")
    
    # Test Coinbase connection
    test_coinbase_connection()

    # Start trading loop in a separate thread
    trading_thread = threading.Thread(target=start_trading_loop, daemon=True)
    trading_thread.start()
    logger.info("Trading loop started in background thread.")

# ---------------------------
# Run App
# ---------------------------
if __name__ == "__main__":
    logger.info("Starting Flask app for development...")
    app.run(host="0.0.0.0", port=8080)
