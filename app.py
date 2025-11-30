from flask import Flask, jsonify
import logging

app = Flask(__name__)

# Check if coinbase_advanced can load
try:
    from coinbase_advanced.client import Client
    COINBASE_CONNECTED = True
except ModuleNotFoundError:
    COINBASE_CONNECTED = False
    logging.error("coinbase_advanced module not installed ❌")

@app.route("/")
def home():
    return "NIJA Trading Bot is alive 🐱‍👤"

@app.route("/status")
def status():
    return jsonify({
        "bot": "running",
        "coinbase_connected": COINBASE_CONNECTED,
        "trades_executed": 0  # replace with real metric in your trading engine
    })
