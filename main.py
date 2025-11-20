# main.py
import os
from flask import Flask, jsonify
from loguru import logger

app = Flask(__name__)

# Try to initialize Coinbase client once, so startup fails early if config is bad
try:
    from nija_client import CoinbaseClient
    client = CoinbaseClient()
    logger.info("CoinbaseClient initialized")
except Exception as e:
    client = None
    logger.exception("Failed to initialize CoinbaseClient at startup")

@app.route("/")
def index():
    status = {
        "service": "NIJA Bot",
        "coinbase_client": "initialized" if client else "not-initialized"
    }
    return jsonify(status)

@app.route("/accounts")
def accounts():
    if not client:
        return jsonify({"error": "coinbase client not initialized"}), 500
    try:
        accts = client.list_accounts()
        # Try to make the accounts JSON-serializable
        return jsonify({"accounts": accts})
    except Exception as e:
        logger.exception("Failed fetching accounts")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
