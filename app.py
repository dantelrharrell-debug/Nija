# app.py
from flask import Flask, render_template_string
import os
import csv
from decimal import Decimal

app = Flask(__name__)

# Trade log file (must match nija_client.py)
LOG_FILE = "trade_log.csv"

# Dummy balance for display if no trades yet
DUMMY_BTC = Decimal("0.0")
DUMMY_USD = Decimal("0.0")

@app.route("/")
def index():
    last_trade = None
    total_btc = Decimal("0.0")

    # Read trade log
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if rows:
                last = rows[-1]
                last_trade = {
                    "timestamp": last["timestamp"],
                    "btc_amount": Decimal(last["btc_amount"]),
                    "usd_value": Decimal(last["usd_value"]),
                    "btc_price": Decimal(last["btc_price"])
                }
                # Sum total BTC bought
                for row in rows:
                    total_btc += Decimal(row["btc_amount"])

    # Fallback if no trades
    if not last_trade:
        last_trade = {
            "timestamp": "N/A",
            "btc_amount": DUMMY_BTC,
            "usd_value": DUMMY_USD,
            "btc_price": DUMMY_USD
        }

    html = f"""
    <html>
    <head>
        <title>Nija Trading Bot Dashboard</title>
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #111; color: #0f0; text-align: center; padding: 50px; }}
            h1 {{ color: #0ff; }}
            .stat {{ margin: 20px; font-size: 1.5em; }}
        </style>
    </head>
    <body>
        <h1>Nija Trading Bot Live Dashboard</h1>
        <div class="stat">Last Trade: {last_trade['btc_amount']} BTC @ ${last_trade['btc_price']} (USD spent: ${last_trade['usd_value']})</div>
        <div class="stat">Last Trade Timestamp (UTC): {last_trade['timestamp']}</div>
        <div class="stat">Total BTC Acquired: {total_btc}</div>
        <div class="stat">Trading Mode: {"LIVE" if os.getenv("TRADING_MODE") == "live" else "SIMULATION"}</div>
    </body>
    </html>
    """
    return render_template_string(html)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
