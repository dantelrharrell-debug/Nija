# app/app.py
import os
from flask import Flask, jsonify

# Import Coinbase helper (defined separately)
from nija_client.check_funded import get_balances, CoinbaseError

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

@app.route("/balance", methods=["GET"])
def balance():
    """
    Returns JSON with balances in funded accounts.
    Example response:
    {
      "status": "ok",
      "balances": [
        {"currency": "USD", "available": "125.89"},
        {"currency": "BTC", "available": "0.0041"}
      ]
    }
    """
    try:
        balances = get_balances()
        return jsonify({"status": "ok", "balances": balances}), 200
    except CoinbaseError as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": "Unexpected error: " + str(e)}), 500
