# nija_bot_web/app.py

from flask import Flask, render_template, jsonify
from threading import Thread
from config import SPOT_TICKERS, FUTURES_TICKERS
from position_manager import get_trade_allocation

app = Flask(__name__)

running = True
account_balance = 15.00  # Example starting balance
positions = []
signals = []

def update_positions():
    """
    Update signals and positions for all tickers (Spot & Futures)
    """
    global positions, signals, account_balance
    signals = []

    for market_type, tickers in [("Spot", SPOT_TICKERS), ("Futures", FUTURES_TICKERS)]:
        for symbol in tickers:
            # Placeholder for VWAP + RSI signal logic
            action = "Long" if symbol in ["BTC/USD", "ETH/USD", "SOL/USD"] else "Short"
            status = "Ready" if symbol in ["BTC/USD", "ETH/USD"] else "Monitoring"

            trade_amount = get_trade_allocation(account_balance)

            # Update existing position or add new
            existing = next((p for p in positions if p["symbol"] == symbol and p["type"] == market_type), None)
            if not existing:
                positions.append({
                    "symbol": symbol,
                    "type": market_type,
                    "side": action,
                    "size": trade_amount,
                    "entry": 35000 if "BTC" in symbol else 1950,  # example entries
                    "pl": 0.00
                })

            signals.append({"symbol": symbol, "type": market_type, "action": action, "status": status})

# Background thread to refresh positions
def bot_loop():
    import time
    while running:
        update_positions()
        time.sleep(2)  # refresh every 2 seconds

Thread(target=bot_loop, daemon=True).start()

# Routes
@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

@app.route("/dashboard/data")
def dashboard_data():
    return jsonify({
        "status": "live" if running else "stopped",
        "account_balance": account_balance,
        "positions": positions,
        "signals": signals
    })

@app.route("/health")
def health_check():
    return jsonify({
        "status": "Flask alive",
        "trading": "live" if running else "stopped",
        "coinbase": "reachable"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)
