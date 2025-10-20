import os
from flask import Flask, jsonify, request
import threading
from nija_bot import trade_loop

app = Flask(__name__)

# Secret for /start endpoint
SECRET_KEY = os.getenv("BOT_SECRET_KEY", "changeme")

@app.route("/")
def index():
    return jsonify({"status": "ok", "bot": "Nija Ultimate AI"}), 200

@app.route("/start")
def start_bot():
    token = request.args.get("token", "")
    if token != SECRET_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    threading.Thread(target=trade_loop, daemon=True).start()
    return jsonify({"status": "started"}), 200

# Optional webhook endpoint
@app.route("/webhook", methods=["POST"])
def webhook():
    token = request.headers.get("X-Webhook-Token")
    if token != os.getenv("TV_WEBHOOK_SECRET"):
        return jsonify({"status":"error","message":"Unauthorized"}), 401
    # Process TradingView alert here
    return jsonify({"status":"ok","message":"Webhook received"}), 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
