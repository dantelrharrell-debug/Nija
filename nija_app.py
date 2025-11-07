# nija_app.py (add below your /test-buy endpoint)
from flask import Flask, jsonify
from nija_client import CoinbaseClient

# Assuming `app` and `client` already exist
# app = Flask(__name__)
# client = CoinbaseClient()

@app.route("/balances", methods=["GET"])
def get_balances():
    """
    Returns account balances with USD equivalents, filtering out zero balances.
    """
    try:
        accounts = client.list_accounts()  # list_accounts returns all accounts from Coinbase
        non_zero = []

        for acc in accounts:
            balance = float(acc.get("balance", {}).get("amount", 0))
            currency = acc.get("balance", {}).get("currency", "USD")
            usd_value = float(acc.get("native_balance", {}).get("amount", 0))  # USD equivalent

            if balance > 0:
                non_zero.append({
                    "currency": currency,
                    "balance": balance,
                    "usd_equivalent": usd_value
                })

        return jsonify({"success": True, "accounts": non_zero})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
