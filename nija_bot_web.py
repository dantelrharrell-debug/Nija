import os
import threading
from flask import Flask, jsonify, request
from nija_bot import trade_loop  # Make sure trade_loop exists in nija_bot.py

app = Flask(__name__)

# Secrets
BOT_SECRET_KEY = os.getenv("BOT_SECRET_KEY", "changeme")
TV_WEBHOOK_SECRET = os.getenv("TV_WEBHOOK_SECRET", "changeme")

@app.route("/")
def index():
    return jsonify({"status": "ok", "bot": "Nija Ultimate AI"}), 200

@app.route("/start")
def start_bot():
    token = request.args.get("token", "")
    if token != BOT_SECRET_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    threading.Thread(target=trade_loop, daemon=True).start()
    return jsonify({"status": "started"}), 200

@app.route("/webhook", methods=["POST"])
def webhook():
    token = request.headers.get("X-Webhook-Token")
    if token != TV_WEBHOOK_SECRET:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    # TODO: process TradingView alert here
    return jsonify({"status": "ok", "message": "Webhook received"}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
