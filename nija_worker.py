# nija_worker.py
import os
import sys
import time
import logging
from decimal import Decimal
from tradingview_ta import TA_Handler, Interval
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from nija_coinbase_client import get_usd_balance, place_order_market_quote

# -----------------------
# Logging
# -----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("nija_worker")

# -----------------------
# PEM file check
# -----------------------
PEM_PATH = os.getenv("COINBASE_API_SECRET_PATH")
if not PEM_PATH:
    logger.error("[NIJA-BALANCE] COINBASE_API_SECRET_PATH not set!")
    sys.exit(1)

def check_pem_file(path: str) -> bool:
    if not os.path.exists(path):
        logger.error(f"[NIJA-BALANCE] PEM file not found at {path}")
        return False
    try:
        with open(path, "rb") as pem_file:
            key_data = pem_file.read()
            serialization.load_pem_private_key(
                key_data,
                password=None,
                backend=default_backend()
            )
        logger.info("[NIJA-BALANCE] PEM file loaded successfully ✅")
        return True
    except Exception as e:
        logger.error(f"[NIJA-BALANCE] Failed to load PEM file: {e}")
        return False

if not check_pem_file(PEM_PATH):
    logger.error("[NIJA-BALANCE] Aborting: fix your PEM file before running the bot.")
    sys.exit(1)

# -----------------------
# Risk parameters
# -----------------------
MIN_PCT = 0.02
MAX_PCT = 0.10
MIN_USD = Decimal("1.00")

def calculate_order_size(equity: Decimal, pct: float) -> Decimal:
    size = equity * Decimal(str(pct))
    if size < MIN_USD:
        size = MIN_USD
    return size.quantize(Decimal("0.01"))  # cents resolution

# -----------------------
# Trading logic
# -----------------------
def decide_trade():
    try:
        handler = TA_Handler(
            symbol="BTCUSD",
            screener="crypto",
            exchange="COINBASE",
            interval=Interval.INTERVAL_1_MINUTE
        )
        analysis = handler.get_analysis()
        rsi = analysis.indicators.get("RSI", 50)
        vwap = analysis.indicators.get("VWAP", 0)
        close = analysis.indicators.get("close", 0)

        if vwap == 0 or close == 0:
            logger.info("[NIJA] Indicators invalid, skipping trade.")
            return None

        equity = get_usd_balance()
        logger.info(f"[NIJA] Current USD balance: {equity}")

        if rsi < 30 and close < vwap:
            pct = 0.05  # or min(MAX_PCT, 0.05)
            return "buy", pct
        elif rsi > 70 and close > vwap:
            pct = 0.05
            return "sell", pct
        return None
    except Exception as e:
        logger.error("[NIJA] decide_trade error: %s", e)
        return None

def place_order(trade_type: str, position_pct: float):
    equity = get_usd_balance()
    if equity < MIN_USD:
        logger.warning("[NIJA] USD balance too low to place order. Skipping...")
        return

    order_size = calculate_order_size(equity, position_pct)
    logger.info(f"[NIJA] Executing {trade_type.upper()} order: ${order_size} ({position_pct*100:.1f}% equity)")

    try:
        response = place_order_market_quote(
            product_id="BTC-USD",
            side="BUY" if trade_type == "buy" else "SELL",
            quote_size=str(order_size)
        )
        logger.info("[NIJA] Order response: %s", response)
    except Exception as e:
        logger.error("[NIJA] Order failed: %s", e)

# -----------------------
# Main worker loop
# -----------------------
def run_worker():
    logger.info("[NIJA] Starting live trading worker (JWT/CDP mode)...")
    while True:
        try:
            trade_signal = decide_trade()
            if trade_signal:
                trade_type, pct = trade_signal
                place_order(trade_type, pct)
            else:
                logger.info("[NIJA] No trade signal. Waiting...")

            time.sleep(10)  # slightly longer to avoid API rate limits
        except KeyboardInterrupt:
            logger.info("[NIJA] Worker stopped by user")
            break
        except Exception as e:
            logger.error("[NIJA] Unexpected error in worker: %s", e)
            time.sleep(5)

# -----------------------
# Run worker if main
# -----------------------
if __name__ == "__main__":
    run_worker()
