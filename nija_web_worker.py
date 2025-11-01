# nija_web_worker.py
from threading import Thread
from flask import Flask, jsonify
import logging
import time

from nija_render_worker import run_worker  # ensure this imports correctly

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_web_worker")

app = Flask(__name__)
_worker_thread = None

@app.route("/")
def index():
    return jsonify({"status": "ok", "worker": bool(_worker_thread and _worker_thread.is_alive())})

def _start_worker_thread():
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return
    _worker_thread = Thread(target=run_worker, daemon=True)
    _worker_thread.start()
    logger.info("[NIJA-WEB] Worker thread started")

# Start worker automatically when module is imported by Gunicorn
_start_worker_thread()
