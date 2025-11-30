# wsgi.py
import logging
from flask import Flask, jsonify
from nija_client import test_coinbase_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija-wsgi")

app = Flask(__name__)

@app.route("/")
def index():
    return "NIJA TRADING BOT — up"

@app.route("/__nija_probe")
def probe():
    """Call the test function and return its dict as JSON."""
    try:
        result = test_coinbase_connection()
        return jsonify(result), 200
    except Exception as e:
        logger.exception("Unexpected probe failure")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
