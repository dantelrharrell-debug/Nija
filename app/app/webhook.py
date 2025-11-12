from flask import Flask, request
from loguru import logger
import threading

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    logger.info(f"Received webhook: {data}")
    # Handle webhook signal here
    return {"status": "ok"}, 200

def start_webhook_server():
    """Run Flask webhook in a separate thread."""
    thread = threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000))
    thread.daemon = True
    thread.start()
    logger.info("Webhook server started on port 5000")
