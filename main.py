# main.py
import os
from flask import Flask, jsonify
from nija_client import CoinbaseClient  # wrapper below

app = Flask(__name__)

# create client once (will raise on missing config)
try:
    client = CoinbaseClient()
except Exception as e:
    # log to stdout so Railway build logs / runtime logs show failure early
    print("Failed to initialize CoinbaseClient:", e)
    client = None

@app.route("/")
def index():
    status = {"service": "NIJA Bot", "coinbase_client": "initialized" if client else "missing"}
    return jsonify(status)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
