# nija_app.py
from flask import Flask, jsonify
import os

# Safe import of CoinbaseClient
try:
    from nija_client import CoinbaseClient
except ImportError as e:
    print(f"❌ Unable to import CoinbaseClient: {e}")
    CoinbaseClient = None

app = Flask(__name__)

# Health check endpoint
@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok", "message": "Nija bot is alive"}), 200

# Optional test endpoint to check Coinbase API
@app.route("/test-coinbase", methods=["GET"])
def test_coinbase():
    if not CoinbaseClient:
        return jsonify({"error": "CoinbaseClient not available"}), 500
    client = CoinbaseClient()
    accounts = client.get_accounts()
    if accounts is None:
        return jsonify({"error": "Unauthorized or API issue"}), 401
    return jsonify({"accounts": accounts}), 200


if __name__ == "__main__":
    # Use port from Render environment variable
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
