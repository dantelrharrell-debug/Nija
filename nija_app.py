# nija_app.py
import os
import time
import logging
from flask import Flask
from nija_client import NijaCoinbaseClient
from tradingview_ta import TA_Handler, Interval, Exchange  # optional, can plug in signals

# ----- Setup Logging -----
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("NIJA-BOT")

# ----- Flask App -----
app = Flask(__name__)

@app.route("/")
def home():
    return "NIJA bot is LIVE! Real trades will execute.", 200

# ----- Initialize Coinbase Client -----
client = NijaCoinbaseClient()

# ----- Trading Config -----
SYMBOL = "BTC-USD"
RISK_PERCENT = 5  # Risk per trade (will clamp 2-10%)
TRADE_INTERVAL = 60  # seconds between signal checks

# Optional: TradingView TA Handler (for signals)
tv = TA_Handler(
    symbol="BTCUSD",
    screener="crypto",
    exchange="COINBASE",
    interval=Interval.INTERVAL_1_MIN
)

# ----- Trading Loop -----
def trade_loop():
    log.info("⚡ NIJA bot is LIVE! Real trades will execute.")
    while True:
        try:
            # --- Step 1: Get account equity ---
            equity = client.get_account_balance("USD")
            position_size = client.calculate_position_size(equity, RISK_PERCENT)

            # --- Step 2: Get trading signal ---
            analysis = tv.get_analysis()
            signal = analysis.summary["RECOMMENDATION"].lower()  # 'buy', 'sell', 'neutral'

            # --- Step 3: Execute trade ---
            if signal in ["buy", "sell"]:
                log.info(f"Signal detected: {signal.upper()}")
                order = client.place_order(
                    symbol=SYMBOL,
                    side=signal,
                    order_type="market",
                    size=position_size
                )
                log.info(f"Order executed: {order}")
            else:
                log.info("No actionable signal detected.")

        except Exception as e:
            log.error(f"Error in trading loop: {e}")

        time.sleep(TRADE_INTERVAL)

# ----- Start Trading Loop in Background -----
import threading
threading.Thread(target=trade_loop, daemon=True).start()

# ----- Run Flask App -----
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
