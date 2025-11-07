# in nija_app.py
from loguru import logger
from flask import Flask, jsonify
import startup_env
from nija_client import NijaCoinbaseClient

app = Flask(__name__)
client = NijaCoinbaseClient()

@app.route("/accounts")
def accounts():
    try:
        data = client.get_accounts()
        # ensure data is JSON-serializable
        return jsonify(data)
    except Exception as e:
        logger.exception("GET /accounts failed")
        # return minimal info to caller; full stack is in logs
        return jsonify({"error": "internal server error", "details": str(e)}), 500
