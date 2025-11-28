from flask import Flask
import logging

app = Flask(__name__)

# Import your funded account check
from nija_client.check_funded import check_funded_accounts

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

@app.before_first_request
def startup_checks():
    # Run the funded account check
    funded = check_funded_accounts()
    if not funded:
        logging.error("❌ No funded accounts found. Exiting.")
        # Stop the container by raising an exception
        raise SystemExit("No funded accounts detected. Shutting down.")

@app.route("/")
def index():
    return "Nija Bot Running!"
