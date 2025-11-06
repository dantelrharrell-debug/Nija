# nija_app.py
from flask import Flask, jsonify
import os

# lightweight import to avoid failing at import-time if nija_client has issues
try:
    from nija_client import CoinbaseClient
except Exception as e:
    CoinbaseClient = None
    client_import_error = str(e)
else:
    client_import_error = None

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija trading service — alive", 200

@app.route("/health")
def health():
    info = {"service": "nija", "status": "ok"}
    # include Coinbase connectivity info if possible
    if CoinbaseClient is None:
        info["coinbase"] = {"status": "unavailable", "error": client_import_error}
        return jsonify(info), 200

    try:
        client = CoinbaseClient()
    except Exception as e:
        info["coinbase"] = {"status": "init_error", "error": str(e)}
        return jsonify(info), 200

    try:
        accounts = client.list_accounts()
        # If accounts is None or empty, report but do not fail HTTP status.
        info["coinbase"] = {"status": "connected", "accounts_count": len(accounts) if accounts is not None else 0}
    except Exception as e:
        info["coinbase"] = {"status": "error", "error": str(e)}
    return jsonify(info), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
