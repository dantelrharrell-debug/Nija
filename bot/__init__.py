import os
import logging
from flask import Flask, jsonify

# ======================
# Logging setup
# ======================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

# ======================
# Attempt to import Coinbase client safely
# ======================
try:
    from coinbase_advanced_py.client import Client
    COINBASE_AVAILABLE = True
    logger.info("coinbase_advanced_py imported successfully.")
except ModuleNotFoundError:
    COINBASE_AVAILABLE = False
    logger.error("coinbase_advanced_py module not installed. Live trading disabled.")

# ======================
# Load Coinbase credentials safely
# ======================
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")
API_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE")

missing_vars = [name for name, val in {
    "COINBASE_API_KEY": API_KEY,
    "COINBASE_API_SECRET": API_SECRET,
    "COINBASE_API_PASSPHRASE": API_PASSPHRASE
}.items() if not val]

if missing_vars:
    logger.warning(f"Missing environment variables: {', '.join(missing_vars)}")

if COINBASE_AVAILABLE and not missing_vars:
    client = Client(
        api_key=API_KEY,
        api_secret=API_SECRET,
        api_passphrase=API_PASSPHRASE
    )
    logger.info("Coinbase client initialized successfully.")
else:
    client = None
    if COINBASE_AVAILABLE:
        logger.warning("Coinbase client not initialized due to missing credentials.")
    else:
        logger.warning("Coinbase client unavailable due to missing module.")

# ======================
# Example trading function (dry-run)
# ======================
def place_order_dry_run():
    if client:
        logger.info("Placing order (dry-run)...")
        # Example: client.create_order(...)   # uncomment when ready
    else:
        logger.info("Skipping order: Coinbase client unavailable or credentials missing.")

# ======================
# Flask app setup
# ======================
app = Flask(__name__)

@app.route("/health")
def health_check():
    status = {
        "coinbase_module_installed": COINBASE_AVAILABLE,
        "client_initialized": bool(client),
        "missing_credentials": missing_vars,
        "status": "ok"
    }
    return jsonify(status)

@app.route("/run-bot")
def run_bot():
    try:
        place_order_dry_run()
        return jsonify({"status": "bot executed successfully"})
    except Exception as e:
        logger.exception("Error running bot:")
        return jsonify({"status": "error", "message": str(e)}), 500

# ======================
# Verification endpoint: confirms Coinbase client can connect safely
# ======================
@app.route("/verify-coinbase")
def verify_coinbase():
    if not client:
        return jsonify({
            "status": "error",
            "message": "Coinbase client unavailable or credentials missing."
        }), 400
    try:
        # Safe test: fetch account list (read-only, no orders)
        accounts = client.get_accounts()
        return jsonify({
            "status": "success",
            "message": f"Coinbase client verified. {len(accounts)} accounts accessible."
        })
    except Exception as e:
        logger.exception("Coinbase verification failed:")
        return jsonify({
            "status": "error",
            "message": f"Verification failed: {str(e)}"
        }), 500

# ======================
# Optional: run Flask locally for debugging
# ======================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
