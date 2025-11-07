from flask import Flask, jsonify
from nija_client import CoinbaseClient
from loguru import logger

app = Flask(__name__)

try:
    client = CoinbaseClient()
except Exception as e:
    logger.error(f"Failed to initialize CoinbaseClient: {e}")
    client = None

@app.route("/")
def index():
    if client is None:
        return jsonify({"error": "CoinbaseClient not initialized"}), 500

    accounts = client.get_accounts()
    results = []
    for a in accounts:
        name = a.get("name", "<unknown>")
        bal = a.get("balance", {})
        results.append({
            "name": name,
            "amount": bal.get("amount", "0"),
            "currency": bal.get("currency", "?")
        })

    return jsonify(results)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
