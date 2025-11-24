from flask import Blueprint, request, jsonify

bp = Blueprint('tradingview', __name__)

@bp.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("Webhook received:", data)
    return jsonify({"status": "success"}), 200
