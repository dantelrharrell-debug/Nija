# nija_app.py
from flask import Flask, jsonify
import os
from nija_client import CoinbaseClient

app = Flask(__name__)

@app.route("/")
def index():
    return jsonify({"service": "nija", "status": "running"}), 200

@app.route("/health")
def health():
    # simple health check that attempts to connect to Coinbase but never raises
    try:
        client = CoinbaseClient()
    except Exception as e:
        return jsonify({"status": "error", "error": f"client_init_failed: {str(e)}"}), 200

    try:
        accounts = client.get_accounts()
        if accounts:
            # Try to compute accounts_count robustly
            if isinstance(accounts, dict):
                data = accounts.get("data") or accounts.get("accounts")
                if isinstance(data, list):
                    count = len(data)
                else:
                    # unknown structure, return raw top-key summary
                    count = None
            else:
                count = None
            return jsonify({"status": "ok", "accounts_count": count}), 200
        else:
            return jsonify({"status": "ok", "accounts_count": None, "note": "no accounts returned (check API keys)"}), 200
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
