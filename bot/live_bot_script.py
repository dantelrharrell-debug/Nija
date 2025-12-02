import os
from coinbase.wallet.client import Client   # ✅ REQUIRED FIX
# bot/live_bot_script.py
import os
from flask import Flask, jsonify, request
from coinbase.wallet.client import Client
import logging

# -----------------------------
# Logging setup
# -----------------------------
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)s | %(message)s")

logger = logging.getLogger(__name__)

# -----------------------------
# Coinbase Client setup
# -----------------------------
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")

if not API_KEY or not API_SECRET:
    logger.error("Missing Coinbase API_KEY or API_SECRET environment variables")
    raise RuntimeError("Coinbase credentials not found! Set COINBASE_API_KEY and COINBASE_API_SECRET")

coinbase_client = Client(API_KEY, API_SECRET)
logger.info("Coinbase client initialized successfully")

# -----------------------------
# Flask app setup
# -----------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return jsonify({"status": "ok", "message": "NIJA Trading Bot API is running"})

@app.route("/accounts")
def get_accounts():
    """
    Returns a list of Coinbase accounts and balances
    """
    try:
        accounts = coinbase_client.get_accounts()
        result = []
        for account in accounts.data:
            result.append({
                "id": account.id,
                "name": account.name,
                "currency": account.currency,
                "balance": account.balance.amount,
                "available": account.available.amount,
                "hold": account.hold.amount
            })
        return jsonify({"accounts": result})
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/buy", methods=["POST"])
def buy():
    """
    Buy a cryptocurrency
    Request JSON example:
    {
        "currency": "BTC",
        "amount": "0.001",
        "payment_method_id": "<your_payment_method_id>"
    }
    """
    try:
        data = request.json
        currency = data.get("currency")
        amount = data.get("amount")
        payment_method_id = data.get("payment_method_id")

        if not currency or not amount or not payment_method_id:
            return jsonify({"error": "Missing parameters"}), 400

        txn = coinbase_client.buy(
            account_id=f"{currency}-USD",
            amount=amount,
            currency=currency,
            payment_method=payment_method_id
        )
        return jsonify({"transaction": txn})
    except Exception as e:
        logger.error(f"Buy error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/sell", methods=["POST"])
def sell():
    """
    Sell a cryptocurrency
    Request JSON example:
    {
        "currency": "BTC",
        "amount": "0.001"
    }
    """
    try:
        data = request.json
        currency = data.get("currency")
        amount = data.get("amount")

        if not currency or not amount:
            return jsonify({"error": "Missing parameters"}), 400

        txn = coinbase_client.sell(
            account_id=f"{currency}-USD",
            amount=amount,
            currency=currency
        )
        return jsonify({"transaction": txn})
    except Exception as e:
        logger.error(f"Sell error: {e}")
        return jsonify({"error": str(e)}), 500

# -----------------------------
# Run Flask app
# -----------------------------
def create_app():
    return app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
