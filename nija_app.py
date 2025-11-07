from flask import Flask, jsonify
from nija_client import CoinbaseClient
from tradingview_ta import TA_Handler
from datetime import datetime

app = Flask(__name__)

# Initialize your clients
coinbase = CoinbaseClient()
# Example TradingView handler; customize symbol/exchange as needed
tv_handler = TA_Handler(
    symbol="BTCUSDT",
    screener="crypto",
    exchange="BINANCE",
    interval="1m"
)

@app.route("/", methods=["GET"])
def status():
    # Basic status
    bot_status = "✅ NIJA Trading Bot is live and operational"

    # Check Coinbase connection
    try:
        coinbase.check_connection()  # Implement a simple ping method in CoinbaseClient
        coinbase_status = "✅ Coinbase connected"
    except Exception:
        coinbase_status = "❌ Coinbase connection failed"

    # Check TradingView connection
    try:
        analysis = tv_handler.get_analysis()
        tv_status = "✅ TradingView connected"
    except Exception:
        tv_status = "❌ TradingView connection failed"

    # Build response
    response = {
        "status": bot_status,
        "coinbase": coinbase_status,
        "tradingview": tv_status,
        "version": "1.0.0",
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

    return jsonify(response)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
