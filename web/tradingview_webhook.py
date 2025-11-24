# web/tradingview_webhook.py
from flask import Blueprint, request, jsonify

# Blueprint name matches what we’ll import in wsgi.py
tradingview_blueprint = Blueprint('tradingview', __name__)

@tradingview_blueprint.route('/webhook', methods=['POST'])
def webhook():
    """
    Handle incoming TradingView webhook POST requests.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON received"}), 400

    # TODO: Add your webhook processing logic here
    print("TradingView webhook received:", data)

    return jsonify({"status": "success"}), 200
