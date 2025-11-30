# wsgi.py
from flask import Flask, jsonify
import threading
import logging
import os

# Import your NIJA bot entry point
try:
    from nija_client import start_bot  # replace with your actual bot function
except ImportError:
    start_bot = None
    logging.error("nija_client.py or start_bot() not found")

app = Flask(__name__)

@app.route("/")
def home():
    return "NIJA Bot is online! Visit /start to launch the bot."

@app.route("/start")
def start():
    if start_bot is None:
        return "Bot function not available", 500

    # Run the bot in a separate thread to avoid blocking the web server
    threading.Thread(target=start_bot, daemon=True).start()
    return "NIJA Bot has been started!"

@app.route("/status")
def status():
    # Optional: simple health check endpoint
    return jsonify({
        "status": "running",
        "bot_available": start_bot is not None,
        "environment": os.environ.get("RAILWAY_ENVIRONMENT", "unknown")
    })

if __name__ == "__main__":
    # Local development
    app.run(host="0.0.0.0", port=8080)
