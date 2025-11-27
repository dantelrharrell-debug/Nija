# app.py
from flask import Flask, jsonify
from nija_client import test_coinbase_connection, COINBASE_CLIENT_AVAILABLE

app = Flask(__name__)

@app.route("/")
def index():
    return "Nija Bot Running!"

@app.route("/debug/coinbase")
def debug_coinbase():
    """Return status of Coinbase client and a fresh connection test."""
    available = bool(COINBASE_CLIENT_AVAILABLE)
    ok = test_coinbase_connection()
    return jsonify({
        "coinbase_module_imported": available,
        "coinbase_connection_test": ok
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
