import os
from flask import Flask, jsonify, request
import threading
from nija_bot import trade_loop

app = Flask(__name__)
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

@app.route("/webhook", methods=["POST"])
def webhook():
    token = request.headers.get("X-Webhook-Token")
    if token != os.getenv("TV_WEBHOOK_SECRET"):
        return jsonify({"status":"error","message":"Unauthorized"}), 401
    return jsonify({"status":"ok","message":"Webhook received"}), 200

if __name__ == "__main__":
    port_str = os.getenv("PORT")
    try:
        port = int(port_str) if port_str else 5000
    except ValueError:
        print(f"⚠️ Invalid PORT value: '{port_str}', using 5000")
        port = 5000

    app.run(host="0.0.0.0", port=port)
