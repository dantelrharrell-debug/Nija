from flask import Blueprint, request, jsonify

tradingview_blueprint = Blueprint('tradingview', __name__)

@tradingview_blueprint.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("Webhook received:", data)
    return jsonify({"status": "success"}), 200
