import sys
import os

# Add the vendor folder to sys.path so Python can find vendored packages
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# Import the Coinbase Advanced Python SDK from vendor
import coinbase_advanced_py as cap

import os
from flask import Flask, jsonify
from nija_bot import TRADING_PAIRS, live_data, ai_signal, get_account_balance

app = Flask(__name__)
WEBHOOK_SECRET = os.getenv("TV_WEBHOOK_SECRET", "mysecret123")


@app.route("/")
def index():
    status = {}
    for pair in TRADING_PAIRS:
        latest_price = None
        if not live_data[pair].empty:
            latest_price = float(live_data[pair]["price"].iloc[-1])
        status[pair] = {
            "latest_price": latest_price,
            "AI_signal": ai_signal(pair),
            "USD_balance": get_account_balance("USD"),
        }
    return jsonify(status), 200


if __name__ == "__main__":
    # For local dev only; production uses gunicorn via Procfile
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
