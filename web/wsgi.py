from flask import Flask
from nija_client import test_coinbase_connection
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


@app.route("/")
def index():
    return "Nija Trading Bot Running!"


# Run Coinbase check on startup
@app.before_first_request
def startup_checks():
    logging.info("Running Coinbase connection test at startup...")
    test_coinbase_connection()


if __name__ == "__main__":
    # Only used for local debugging; Gunicorn will use this file as WSGI
    logging.info("Starting Flask app directly on 0.0.0.0:8080")
    app.run(host="0.0.0.0", port=8080)
