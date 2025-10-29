# nija_client.py
import os
import sys
import logging
from flask import Flask, jsonify

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Remove potential shadowing folders in project root ---
CWD = os.getcwd()
shadow_folders = ["coinbase_advanced_py", "coinbase-advanced-py"]
for folder in shadow_folders:
    path = os.path.join(CWD, folder)
    if os.path.exists(path):
        try:
            import shutil
            shutil.rmtree(path)
            logger.info(f"[NIJA-SHIM] Removed shadowing folder: {path}")
        except Exception as e:
            logger.warning(f"[NIJA-SHIM] Failed to remove shadowing folder: {path} ({e})")

# Remove current working directory from sys.path to prevent namespace issues
if CWD in sys.path:
    sys.path.remove(CWD)
    logger.info("[NIJA-SHIM] Removed CWD from sys.path to prevent shadowing")

# --- Try importing CoinbaseClient ---
CoinbaseClient = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA-SHIM] Successfully imported CoinbaseClient")
except ModuleNotFoundError:
    logger.warning("[NIJA-SHIM] CoinbaseClient not available. Using DummyClient instead.")
except Exception as e:
    logger.warning(f"[NIJA-SHIM] Error importing CoinbaseClient: {e}")

# --- Dummy client as fallback ---
class DummyClient:
    def get_accounts(self):
        logger.warning("[DummyClient] get_accounts called - no live trading!")
        return []

    def place_order(self, *args, **kwargs):
        logger.warning("[DummyClient] place_order called - no live trading!")
        return {"status": "dummy"}

# --- Instantiate the appropriate client ---
client = CoinbaseClient() if CoinbaseClient else DummyClient()
logger.info(f"[NIJA-SHIM] Using client: {'CoinbaseClient' if CoinbaseClient else 'DummyClient'}")
logger.info(f"[NIJA-SHIM] SANDBOX={os.environ.get('SANDBOX', 'None')}")

# --- Flask health check endpoint ---
app = Flask(__name__)
running = True  # Toggle based on whether trading loop is active

@app.route("/health", methods=["GET"])
def health_check():
    coinbase_status = "unavailable"
    try:
        if isinstance(client, CoinbaseClient):
            accounts = client.get_accounts()
            coinbase_status = "ok" if accounts is not None else "unreachable"
        else:
            coinbase_status = "dummy_client"
    except Exception:
        coinbase_status = "error"

    return jsonify({
        "status": "alive",
        "trading": "live" if running else "stopped",
        "coinbase": coinbase_status
    })

# --- Optional: run Flask if script executed directly ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
