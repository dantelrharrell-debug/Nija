# app/app/webhook.py
from loguru import logger
from flask import Flask, request, jsonify  # Example using Flask

def start_webhook_server(client):
    """
    Starts a simple webhook server that listens for Coinbase signals.
    """
    app = Flask(__name__)

    @app.route("/webhook", methods=["POST"])
    def webhook():
        data = request.json
        logger.info(f"Received webhook data: {data}")
        # Here you can call your client to make trades
        return jsonify({"status": "received"}), 200

    logger.info("Starting webhook server on port 5000...")
    app.run(host="0.0.0.0", port=5000)
