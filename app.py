from flask import Flask, jsonify
import logging
import os
import time

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# Attempt to import Coinbase client safely
try:
    from coinbase_advanced.client import Client
except ModuleNotFoundError:
    Client = None
    logging.error("coinbase_advanced module not installed. Live trading disabled.")

# Flask app
app = Flask(__name__)

# Startup info collector
def get_startup_info():
    return {
        "container_start": time.strftime("%Y-%m-%dT%H:%M:%S.000000000Z", time.gmtime()),
        "gunicorn": {
            "workers": 2,
            "worker_class": "gthread",
            "threads": 2,
            "bind": "0.0.0.0:8080",
            "loglevel": "debug",
            "capture_output": True,
            "worker_connections": 1000,
            "limit_request_fields": 100,
            "limit_request_field_size": 8190,
            "limit_request_line": 4094,
            "timeout": 120,
            "graceful_timeout": 30,
            "keepalive": 2,
            "reload": False,
            "preload_app": False,
            "reuse_port": False,
            "daemon": False,
            "chdir": "/app"
        },
        "optional_modules_skipped": [
            "nija_client.optional_app_module1",
            "nija_client.optional_app_module2"
        ]
    }

# Endpoint to get startup info
@app.route("/bot_status")
def bot_status():
    info = get_startup_info()
    return jsonify(info)

# Coinbase connection test
def test_coinbase_connection():
    if Client is None:
        logging.warning("Coinbase client unavailable. Live trading disabled.")
        return {"status": "client_missing"}

    try:
        client = Client(
            api_key=os.environ.get("COINBASE_API_KEY"),
            api_secret=os.environ.get("COINBASE_API_SECRET"),
            api_sub=os.environ.get("COINBASE_API_SUB", None)
        )
        # Check account balances to confirm funding
        accounts = client.get_accounts()  # returns list of accounts
        funded_accounts = [a for a in accounts if float(a.get("balance", {}).get("amount", 0)) > 0]
        if funded_accounts:
            logging.info(f"Live trading ENABLED. Funded accounts: {len(funded_accounts)}")
            return {"status": "live", "funded_accounts": len(funded_accounts)}
        else:
            logging.info("No funded accounts. Trading disabled.")
            return {"status": "no_funds", "funded_accounts": 0}

    except Exception as e:
        logging.error(f"Coinbase connection failed: {e}")
        return {"status": "error", "message": str(e)}

# Endpoint to check Coinbase account/funding
@app.route("/coinbase_status")
def coinbase_status():
    return jsonify(test_coinbase_connection())

if __name__ == "__main__":
    # Only used if running directly
    app.run(host="0.0.0.0", port=5000)
