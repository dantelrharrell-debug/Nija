# main.py
import os
import logging
from flask import Flask, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200

@app.route("/coinbase-status")
def coinbase_status():
    try:
        # lazy import after run-time install
        from nija_client import get_coinbase_client, COINBASE_ACCOUNT_ID
    except Exception as e:
        logger.exception("coinbase client import failed")
        return jsonify({"ok": False, "reason": "coinbase client import failed", "error": str(e)}), 500

    try:
        client = get_coinbase_client()
        accounts = client.get_accounts()
        funded = None
        acct_id = os.getenv("COINBASE_ACCOUNT_ID")
        if acct_id:
            funded = next((a for a in accounts if a.get("id") == acct_id), None)
        return jsonify({"ok": True, "accounts_count": len(accounts), "funded_account_found": bool(funded)})
    except Exception as e:
        logger.exception("coinbase connection check failed")
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
