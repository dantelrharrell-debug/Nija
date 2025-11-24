from flask import Blueprint, request, jsonify

tradingview_blueprint = Blueprint("tradingview", __name__)

@tradingview_blueprint.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json() or {}
    # Live bot logic goes here
    return jsonify({"status": "received", "data": data, "live": False}), 200
