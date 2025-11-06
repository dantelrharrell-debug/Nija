# nija_app.py
from flask import Flask, jsonify
from nija_client import CoinbaseClient

app = Flask(__name__)

# Initialize client on startup
try:
    client = CoinbaseClient()
    accounts = client.list_accounts()
except Exception as e:
    print("Failed to initialize CoinbaseClient:", e)
    accounts = []

@app.route("/")
def index():
    if accounts:
        return jsonify({"status": "live", "accounts": accounts})
    return jsonify({"status": "error", "message": "No accounts found or API keys invalid."})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
