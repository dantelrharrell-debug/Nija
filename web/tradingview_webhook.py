# web/tradingview_webhook.py
from flask import Blueprint, request, jsonify, current_app

# define blueprint as `bp` (legacy) and also export a clear name
bp = Blueprint("tradingview_webhook", __name__)
tradingview_blueprint = bp  # alias for imports that expect tradingview_blueprint

@bp.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(silent=True)
        current_app.logger.info("TradingView webhook received: %s", data)
        # --- TODO: add your actual webhook processing here ---
        # Example minimal reply:
        return jsonify({"status": "received", "payload": data}), 200
    except Exception as exc:
        current_app.logger.exception("Error handling TradingView webhook")
        return jsonify({"status": "error", "message": str(exc)}), 500
