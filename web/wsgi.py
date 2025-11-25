from flask import Flask
import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

app = Flask(__name__)

# Health check route
@app.route("/")
def index():
    return "Nija Trading Bot Running!"

# Optional: Test env variables safely at runtime
def verify_env_vars():
    keys = ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_API_SUB", "COINBASE_PEM_CONTENT"]
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        logging.error(f"Missing environment variables: {missing}")
        raise RuntimeError(f"Missing environment variables: {missing}")
    logging.info("All required environment variables are set.")

# Only run this check when running standalone (not when Gunicorn loads WSGI)
if __name__ == "__main__":
    verify_env_vars()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
