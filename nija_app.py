# nija_app.py
from flask import Flask, jsonify
from loguru import logger
from nija_client import client  # safe import
import os

app = Flask(__name__)

PRIMARY_CURRENCY = "USD"  # change to your main currency

@app.route("/health")
def health():
    # Check required environment variables
    missing = [k for k in ("COINBASE_API_KEY", "COINBASE_API_SECRET") if not os.getenv(k)]
    if missing:
        return jsonify({"ok": False, "missing_env": missing}), 500

    try:
        accounts = client.get_accounts()
        if not accounts:
            return jsonify({"ok": False, "funded": False, "error": "No accounts returned"}), 500

        # Find first funded account
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
