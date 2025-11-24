# web/tradingview_webhook.py
from flask import Blueprint, request, jsonify

# Define the blueprint as 'bp' so imports match
bp = Blueprint('tradingview', __name__)

@bp.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON received"}), 400

    # Log the received data (can be replaced with actual trading logic)
    print("TradingView webhook received:", data)

    return jsonify({"status": "success"}), 200
