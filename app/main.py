# main.py
import os
import logging
import subprocess
import sys
from flask import Flask, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

# --- Required env vars (checked at startup) ---
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE")
COINBASE_ACCOUNT_ID = os.environ.get("COINBASE_ACCOUNT_ID")
GITHUB_PAT = os.environ.get("GITHUB_PAT")  # used only if installing from GitHub

# minimal sanity check (don't crash if optional is missing)
missing = [k for k,v in {
    "COINBASE_API_KEY": COINBASE_API_KEY,
    "COINBASE_API_SECRET": COINBASE_API_SECRET,
    "COINBASE_API_PASSPHRASE": COINBASE_API_PASSPHRASE
}.items() if not v]

if missing:
    logger.warning("Missing Coinbase env vars at startup (some endpoints will fail): %s", missing)

# --- Ensure coinbase_advanced is importable. If not, try to install at runtime (using GITHUB_PAT) ---
_client_available = False
try:
    from coinbase_advanced.client import Client
    _client_available = True
    logger.info("coinbase_advanced imported from environment.")
except Exception:
    logger.warning("coinbase_advanced not importable. Attempting runtime install using GITHUB_PAT.")
    if not GITHUB_PAT:
        logger.error("GITHUB_PAT not provided. Cannot install coinbase_advanced at runtime.")
    else:
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "--no-cache-dir",
                f"git+https://{GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"
            ])
            # try import again
            from coinbase_advanced.client import Client  # noqa: F401
            _client_available = True
            logger.info("✅ Installed & imported coinbase_advanced at runtime.")
        except Exception as e:
            logger.exception("Failed to install/import coinbase_advanced at runtime: %s", e)
            _client_available = False

def get_coinbase_client():
    if not _client_available:
        raise RuntimeError("coinbase_advanced package not available")

    # create client; adapt args if your SDK version expects different names
    return Client(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET, api_passphrase=COINBASE_API_PASSPHRASE)

@app.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200

@app.route("/coinbase-status")
def coinbase_status():
    if not _client_available:
        return jsonify({"ok": False, "reason": "coinbase client not available"}), 500

    try:
        client = get_coinbase_client()
        accounts = client.get_accounts()
        funded = None
        if COINBASE_ACCOUNT_ID:
            funded = next((a for a in accounts if a.get("id") == COINBASE_ACCOUNT_ID), None)
        return jsonify({
            "ok": True,
            "accounts_count": len(accounts),
            "funded_account_found": bool(funded)
        })
    except Exception as e:
        logger.exception("coinbase connection check failed")
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    # dev run
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
