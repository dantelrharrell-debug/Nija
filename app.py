from flask import Flask, jsonify
import os
import logging

app = Flask(__name__)

# Function to get startup info (hardcoded from your log snippet)
def get_startup_info():
    return {
        "container_start": "2025-11-28T21:37:08.000000000Z",
        "gunicorn": {
            "workers": 2,
            "worker_class": "gthread",
            "threads": 2,
            "bind": "0.0.0.0:8080",
            "loglevel": "debug",
            "capture_output": True
        },
        "options": {
            "reuse_port": False,
            "chdir": "/app",
            "worker_connections": 1000,
            "daemon": False,
            "timeout": 120,
            "graceful_timeout": 30,
            "keepalive": 2,
            "reload": False
        },
        "optional_modules_skipped": [
            "nija_client.optional_app_module1",
            "nija_client.optional_app_module2"
        ]
    }

@app.route("/bot_status")
def bot_status():
    status = {
        "coinbase_module_installed": False,
        "coinbase_connected": False,
        "live_trading": False,
        "bot_active": False,
        "balances": {},
        "errors": [],
        "startup_info": get_startup_info()
    }

    # Coinbase module check
    try:
        from coinbase_advanced.client import Client
        status["coinbase_module_installed"] = True
    except ModuleNotFoundError:
        status["errors"].append("coinbase_advanced module not installed.")
        return jsonify(status), 500

    # Coinbase API keys
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    live_trading_flag = os.environ.get("LIVE_TRADING", "0")  # "1" if live trading enabled

    if not api_key or not api_secret:
        status["errors"].append("Coinbase API key or secret not set.")
        return jsonify(status), 500

    status["live_trading"] = live_trading_flag == "1"

    # Check bot running (simple example: check env flag)
    status["bot_active"] = os.environ.get("BOT_RUNNING", "1") == "1"

    # Try connecting to Coinbase
    try:
        client = Client(api_key=api_key, api_secret=api_secret)
        accounts = client.get_accounts()
        balances = {a['currency']: a['balance'] for a in accounts}
        status["coinbase_connected"] = True
        status["balances"] = balances
    except Exception as e:
        status["errors"].append(str(e))

    return jsonify(status)
