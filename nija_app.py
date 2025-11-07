from flask import Flask, jsonify
from nija_client import client  # your Coinbase client

app = Flask(__name__)

@app.route("/")
def index():
    return "NIJA bot is LIVE! Real trades will execute."

@app.route("/accounts")
def accounts():
    try:
        # Fetch accounts from Coinbase
        accounts_data = client.get_accounts()  # make sure this method exists in your client
        result = []
        for acc in accounts_data:
            result.append({
                "id": acc.id,
                "name": acc.name,
                "currency": acc.currency,
                "balance": str(acc.balance),
                "available": str(acc.available),
                "hold": str(acc.hold)
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
