from flask import Flask, jsonify
from nija_client import get_coinbase_client, test_coinbase_connection, LIVE_TRADING

app = Flask(__name__)

# Initialize Coinbase client on startup
coinbase_client = get_coinbase_client()

@app.before_first_request
def startup_checks():
    if LIVE_TRADING:
        test_coinbase_connection()
    else:
        app.logger.warning("LIVE_TRADING is disabled. Skipping Coinbase connection test.")

# Basic health check endpoint
@app.route("/")
def index():
    return jsonify({"status": "Nija Bot Running!", "live_trading": LIVE_TRADING})

# Optional endpoint to list Coinbase accounts
@app.route("/accounts")
def accounts():
    if not coinbase_client:
        return jsonify({"error": "Coinbase client not initialized"}), 400
    try:
        accounts = coinbase_client.get_accounts()
        return jsonify({"accounts": accounts})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Only used for local testing; Gunicorn will override
    app.run(host="0.0.0.0", port=8080)
