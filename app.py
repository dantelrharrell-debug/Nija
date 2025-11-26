from flask import Flask
from nija_client import test_coinbase_connection
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

@app.before_first_request
def startup_checks():
    logging.info("Running startup checks...")
    if not test_coinbase_connection():
        logging.error("Coinbase test failed. Exiting container...")
        # Stop Flask app without terminal
        import os
        os._exit(1)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
