from flask import Flask, jsonify
from nija_client import CoinbaseClient  # your client class

app = Flask(__name__)

@app.route("/health")
def health():
    try:
        client = CoinbaseClient()
        accounts = client.get_accounts()  # or whatever method fetches balances
        return jsonify({"status": "ok", "accounts": accounts})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})
