from flask import Blueprint, request, jsonify, current_app

def create_tradingview_bp():
    bp = Blueprint("tradingview", __name__)

    @bp.route("/webhook", methods=["POST"])
    def webhook():
        # Local import or use current_app to avoid top-level circular imports
        try:
            payload = request.get_json(silent=True)
        except Exception:
            payload = None

        # Basic logging — replace with real validation/processing
        current_app.logger.debug("TradingView webhook payload: %r", payload)

        # Example minimal validation (customize as needed)
        if not payload:
            return jsonify({"error": "invalid json"}), 400

        # TODO: enqueue job / verify signature / call internal services
        # For now, return simple success response expected by most webhooks
        return jsonify({"status": "ok"}), 200

    return bp

# Convenience export so code that does "from web.tradingview_webhook import bp" keeps working
bp = create_tradingview_bp()
