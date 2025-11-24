from flask import Blueprint, request, jsonify

# exported symbol expected by the app
bp = Blueprint("tradingview", __name__)

@bp.route("/webhook", methods=["POST"])
def webhook():
    # local imports here avoid circular imports if other app modules import this module
    try:
        payload = request.get_json(silent=True)
    except Exception:
        payload = None

    # TODO: replace the following with your real handling logic
    # e.g. validate signature, enqueue a job, call internal services, etc.
    print("TradingView webhook received:", payload)

    # return a JSON response that TradingView (or your runner) expects
    return jsonify({"status": "ok"}), 200
