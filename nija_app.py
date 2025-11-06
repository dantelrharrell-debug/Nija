# nija_app.py
from flask import Flask, jsonify
from nija_client import get_account_balance

app = Flask(__name__)

@app.route("/")
def home():
    return "NIJA Trading Bot API is live!"

@app.route("/debug_accounts")
def debug_accounts():
    """
    Returns a JSON of all accounts accessible via your Coinbase API keys.
    This will help verify which account is funded.
    """
    accounts = get_account_balance()
    return jsonify(accounts)

if __name__ == "__main__":
    app.run(debug=True)
