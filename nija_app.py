from flask import Flask, jsonify
from nija_client import get_usd_spot_balance  # Make sure this function exists

app = Flask(__name__)

@app.route("/")
def home():
    return "NIJA Trading Bot is running. Use /status for bot info."

@app.route("/status")
def status():
    try:
        usd_balance = get_usd_spot_balance()  # Returns Decimal or float
        trading_status = "LIVE"  # You can make this dynamic if you have a flag
        return jsonify({
            "bot_status": trading_status,
            "usd_balance": float(usd_balance)  # convert Decimal to float
        })
    except Exception as e:
        return jsonify({
            "bot_status": "ERROR",
            "error": str(e)
        }), 500

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
