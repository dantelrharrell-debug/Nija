# wsgi.py
from flask import Flask, jsonify
import threading
import logging
import os
import time

# Import your NIJA bot entry point
try:
    from nija_client import start_bot  # replace with your actual bot function
except ImportError:
    start_bot = None
    logging.error("nija_client.py or start_bot() not found")

app = Flask(__name__)

@app.route("/")
def home():
    return "NIJA Bot is online and running!"

@app.route("/status")
def status():
    # Simple health check endpoint
    return jsonify({
        "status": "running",
        "bot_available": start_bot is not None,
        "environment": os.environ.get("RAILWAY_ENVIRONMENT", "unknown")
    })

def launch_bot():
    if start_bot is None:
        logging.error("Bot function not available")
        return
    logging.info("Starting NIJA Bot...")
    start_bot()  # Run your bot's main function

# Start the bot in a separate thread to avoid blocking Gunicorn
threading.Thread(target=launch_bot, daemon=True).start()

if __name__ == "__main__":
    # Local development
    app.run(host="0.0.0.0", port=8080)
