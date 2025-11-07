# nija_app.py
from flask import Flask, jsonify
from loguru import logger
from nija_client import client  # safe import now
import os

app = Flask(__name__)
PRIMARY_CURRENCY = "USD"  # main funded account

# -----------------------------
# Health check route
# -----------------------------
@app.route("/health")
def health():
    missing = [k for k in ("COINBASE_API_KEY","COINBASE_API_SECRET") if not os.getenv(k)]
    if missing:
        return jsonify({"ok": False, "missing_env": missing}), 500

    try:
        accounts = client.get_accounts()
        if not accounts:
            return jsonify({"ok": False, "funded": False, "error": "No accounts returned"}), 500

        # Find funded account in primary currency
        funded_account = next(
            (acct for acct in accounts
             if acct["balance"]["currency"] == PRIMARY_CURRENCY
             and float(acct["balance"]["amount"]) > 0),
            None
        )

        if funded_account:
            balance_amount = float(funded_account["balance"]["amount"])
            return jsonify({
                "ok": True,
                "funded": True,
                "funded_account": funded_account["id"],
                "balance": balance_amount,
                "currency": PRIMARY_CURRENCY
            })
        else:
            return jsonify({
                "ok": True,
                "funded": False,
                "message": f"No funded {PRIMARY_CURRENCY} accounts found"
            })

    except Exception as e:
        logger.exception("Health check failed")
        return jsonify({"ok": False, "error": str(e)}), 500

# -----------------------------
# Root route
# -----------------------------
@app.route("/")
def index():
    return jsonify({"message": "NIJA trading bot is running"})

# -----------------------------
# Run app
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
