# web/wsgi.py
import os
import logging
from dotenv import load_dotenv

# ✅ Load environment variables at the very start
load_dotenv()  # loads from .env in project root

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Verify Coinbase environment variables
logging.info(f"COINBASE_API_KEY found? {'Yes' if os.getenv('COINBASE_API_KEY') else 'No'}")
logging.info(f"COINBASE_API_SECRET found? {'Yes' if os.getenv('COINBASE_API_SECRET') else 'No'}")
logging.info(f"COINBASE_API_SUB found? {'Yes' if os.getenv('COINBASE_API_SUB') else 'No'}")

from flask import Flask
from nija_client import test_coinbase_connection  # import AFTER env loaded

app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Nija Trading Bot Running!"

# Startup check: test Coinbase connection
@app.before_first_request
def startup_checks():
    test_coinbase_connection()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
