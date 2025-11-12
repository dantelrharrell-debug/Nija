from flask import Flask, request
from loguru import logger

app = Flask(__name__)

def start_webhook_server():
    logger.info("Starting webhook server...")
    
    @app.route("/webhook", methods=["POST"])
    def webhook():
        data = request.json
        logger.info(f"Received webhook: {data}")
        return {"status": "success"}

    app.run(host="0.0.0.0", port=5000)
