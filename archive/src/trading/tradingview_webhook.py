# src/trading/tradingview_webhook.py
from flask import Blueprint, request, jsonify, current_app
from src import config

# canonical Blueprint object
_bp = Blueprint("tradingview", __name__)

@_bp.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    current_app.logger.info("TradingView webhook payload: %s", data)

    if not data:
        return jsonify({"error": "No JSON received"}), 400

    # Minimal validation — adjust to match your TradingView format
    required_keys = ("action", "ticker", "strategy", "price")
    if not any(k in data for k in required_keys):
        return jsonify({"error": "Missing expected keys"}), 400

    # Safety: do not trade unless LIVE_TRADING env is enabled
    if not config.LIVE_TRADING:
        current_app.logger.info("LIVE_TRADING=0 -> Test mode, no trade executed.")
        return jsonify({"status": "received", "live": False}), 200

    # Live trading path (ensure nija_client implements execute_trade safely)
    try:
        from src.nija_client import CoinbaseClient
        client = CoinbaseClient()
        # NOTE: implement idempotency & sizing inside execute_trade
        result = client.execute_trade(data)
        return jsonify({"status": "received", "live": True, "result": result}), 200
    except Exception as e:
        current_app.logger.exception("Error executing trade")
        return jsonify({"error": "trade failed", "details": str(e)}), 500

# export common names so any previous import style works
bp = _bp
tradingview_blueprint = _bp
