from flask import Flask, jsonify
from nija_client import CoinbaseClient  # matches the class in nija_client.py

app = Flask(__name__)

@app.route("/health")
def health():
    try:
        client = CoinbaseClient()
        accounts = client.get_accounts()  # fetch balances
        return jsonify({"status": "ok", "accounts": accounts})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
