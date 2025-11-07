# nija_app.py
from flask import Flask, jsonify
from startup_env import *
from nija_client import CoinbaseClient

app = Flask(__name__)
client = CoinbaseClient()

@app.route("/")
def index():
    return "Nija bot is live! 🚀"

@app.route("/accounts")
def accounts():
    try:
        data = client.get_accounts()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
