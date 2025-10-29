# --- safe_env.py (paste at top of nija_live_snapshot.py or create this file and import)
import os
import logging

logger = logging.getLogger("nija_safe_env")

def get_path_env(env_name: str, required: bool = False):
    """Return path string or None. If required and missing, raise ValueError."""
    val = os.environ.get(env_name)
    if val is None or val == "":
        if required:
            raise ValueError(f"Environment variable {env_name} is required but is not set.")
        logger.warning("Env var %s not set", env_name)
        return None
    if not isinstance(val, (str, bytes, os.PathLike)):
        raise ValueError(f"Environment variable {env_name} must be a path string.")
    return str(val)

# Example usage in nija_live_snapshot.py:
# from safe_env import get_path_env, logger
# COINBASE_API_SECRET_PATH = get_path_env("COINBASE_API_SECRET_PATH")

#!/usr/bin/env python3
# nija_live_snapshot.py
import os
import logging
import threading
from coinbase.rest import RESTClient  # Coinbase RESTClient
from flask import Flask, jsonify

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Environment Variables ---
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET_PATH = os.getenv("COINBASE_API_SECRET")
COINBASE_PASSPHRASE = os.getenv("COINBASE_PASSPHRASE")
SANDBOX = os.getenv("SANDBOX", None)

# --- Validate PEM Key ---
if not os.path.isfile(COINBASE_API_SECRET_PATH):
    logger.error(f"[NIJA] PEM file not found: {COINBASE_API_SECRET_PATH}")
    raise FileNotFoundError(f"PEM key missing at {COINBASE_API_SECRET_PATH}")

# --- Initialize Coinbase REST Client ---
try:
    client = RESTClient(api_key=COINBASE_API_KEY,
                        api_secret=COINBASE_API_SECRET_PATH,
                        passphrase=COINBASE_PASSPHRASE,
                        sandbox=SANDBOX)
    logger.info("[NIJA] Live client instantiated via RESTClient")
except Exception as e:
    logger.error(f"[NIJA] Failed to initialize RESTClient: {e}")
    raise e

# --- Trading Helper Functions ---
def get_accounts():
    return client.get_accounts()

def place_order(*args, **kwargs):
    return client.place_order(*args, **kwargs)

def check_live_status():
    try:
        accounts = get_accounts()
        if accounts:
            logger.info("[NIJA] ✅ Live trading ready")
            return True
        else:
            logger.warning("[NIJA] No accounts returned by RESTClient")
            return False
    except Exception as e:
        logger.warning(f"[NIJA] ❌ Nija live check failed: {e}")
        return False

# --- Automatic Startup Check ---
def startup_live_check():
    logger.info("[NIJA] Performing startup live check...")
    if check_live_status():
        logger.info("[NIJA] ✅ Nija trading is LIVE!")
    else:
        logger.error("[NIJA] ❌ Nija trading NOT live! Check PEM/API keys.")

startup_live_check()

# --- Flask Health Endpoint ---
app = Flask(__name__)

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "alive",
        "trading": "live" if check_live_status() else "stopped"
    })

# --- Trading Loop ---
def trading_loop():
    logger.info("[NIJA] Starting trading loop...")
    import time
    while True:
        try:
            # Example: fetch accounts (replace with actual strategy)
            accounts = get_accounts()
            logger.info(f"[NIJA] Accounts: {accounts}")
            # --- PLACE TRADING LOGIC HERE ---
            time.sleep(60)  # wait 1 min between cycles
        except Exception as e:
            logger.error(f"[NIJA] Trading loop exception: {e}")
            time.sleep(10)

# --- Run Trading Loop in Background ---
trading_thread = threading.Thread(target=trading_loop, daemon=True)
trading_thread.start()

# --- Run Flask App for Render ---
if __name__ == "__main__":
    logger.info("[NIJA] Starting Flask server for health endpoint")
    app.run(host="0.0.0.0", port=8080)
