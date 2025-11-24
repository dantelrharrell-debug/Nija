# web/tradingview_webhook.py
# Compatibility shim so imports of `web.tradingview_webhook` succeed
# It will try to import the real package; if unavailable it provides
# a minimal no-op blueprint so the app can boot.

from flask import Blueprint, request, jsonify

def _make_noop_blueprint():
    bp = Blueprint("tradingview_webhook", __name__)

    @bp.route("/tradingview/webhook", methods=["POST"])
    def noop_webhook():
        # minimal response so external services don't fail
        payload = request.get_json(silent=True)
        return jsonify({"status":"shim-ok","received": bool(payload)}), 200

    return bp

try:
    # primary: new package name (if your package installs as tradingview_webhook)
    # adjust attribute names below if your package exports different names
    from tradingview_webhook import blueprint as tradingview_blueprint  # common pattern
    tradingview_bp = tradingview_blueprint
except Exception:
    try:
        # alternate locations used by some forks
        from tradingview_webhook.web import blueprint as tradingview_blueprint
        tradingview_bp = tradingview_blueprint
    except Exception:
        # fallback: expose a simple blueprint so app startup won't fail
        tradingview_bp = _make_noop_blueprint()

# Export a consistent name the app expects (e.g., register_blueprint(tradingview_bp))
blueprint = tradingview_bp
