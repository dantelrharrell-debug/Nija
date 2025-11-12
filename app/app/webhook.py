# app/webhook.py
import os
import time
from threading import Thread
from flask import Flask, request, jsonify
from loguru import logger
import queue

def start_webhook_server(signal_queue: "queue.Queue"):
    """
    Start a Flask webhook server in a background thread and push incoming
    TradingView-style JSON alerts into signal_queue.
    """

    app = Flask("nija-webhook")
    TV_SECRET = os.getenv("TV_WEBHOOK_SECRET")

    @app.route("/tv-webhook", methods=["POST"])
    def tv_webhook():
        # Optional header secret check
        if TV_SECRET:
            header_secret = request.headers.get("X-TV-Webhook-Secret") or request.headers.get("tv-webhook-secret")
            if not header_secret or header_secret != TV_SECRET:
                logger.warning("Webhook rejected: invalid secret header")
                return jsonify({"ok": False, "error": "invalid secret"}), 403

        try:
            payload = request.get_json(force=True)
        except Exception as e:
            logger.warning("Webhook bad json: %s", e)
            return jsonify({"ok": False, "error": "bad json"}), 400

        side = payload.get("side") or payload.get("action") or payload.get("signal")
        product_id = payload.get("product_id") or payload.get("symbol") or payload.get("pair")
        ts = int(time.time())

        if not side or not product_id:
            logger.warning("Webhook missing side/product_id: %s", payload)
            return jsonify({"ok": False, "error": "missing side or product_id"}), 400

        signal = {
            "side": side.lower(),
            "product_id": product_id,
            "raw": payload,
            "received_at": ts,
        }

        try:
            signal_queue.put_nowait(signal)
            logger.info("Webhook enqueued signal: %s %s", signal["side"], signal["product_id"])
            return jsonify({"ok": True}), 200
        except Exception as e:
            logger.error("Failed to enqueue webhook signal: %s", e, exc_info=True)
            return jsonify({"ok": False, "error": "enqueue failed"}), 500

    def run():
        port = int(os.getenv("WEBHOOK_PORT", 8000))
        # Use host 0.0.0.0 so container can receive requests
        app.run(host="0.0.0.0", port=port, threaded=True)

    t = Thread(target=run, daemon=True)
    t.start()
    logger.info("Webhook server started (background thread) on port %s", os.getenv("WEBHOOK_PORT", 8000))
    return t
