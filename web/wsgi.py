# wsgi.py
import os
import logging
from flask import Flask
from nija_client import test_coinbase_connection

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

def run_startup_checks():
    """Run all checks at startup."""
    # Check Coinbase environment variables
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")

    if not all([api_key, api_secret, api_sub]):
        logging.error(
            "Coinbase environment variables missing! "
            "COINBASE_API_KEY=%s, COINBASE_API_SECRET=%s, COINBASE_API_SUB=%s",
            api_key, api_secret, api_sub
        )
        return False

    # Test Coinbase connection
    try:
        test_coinbase_connection()
        logging.info("Coinbase connection successful ✅")
    except Exception as e:
        logging.error("Coinbase connection failed: %s", e)
        return False

    return True

if __name__ == "__main__":
    # Run startup checks before serving requests
    if run_startup_checks():
        logging.info("Starting Flask app...")
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
    else:
        logging.error("Startup checks failed. Exiting container.")
        exit(1)
