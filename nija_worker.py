# -----------------------
# Preflight variable check
# -----------------------
import os

print("COINBASE_API_KEY:", "FOUND" if os.getenv("COINBASE_API_KEY") else "MISSING")
print("COINBASE_API_SECRET:", "FOUND" if os.getenv("COINBASE_API_SECRET") else "MISSING")
print("PEM_PATH:", os.getenv("COINBASE_API_SECRET_PATH"))
pem_content = os.getenv("COINBASE_PEM_CONTENT")
print("PEM_CONTENT LENGTH:", len(pem_content) if pem_content else "MISSING")

# -----------------------
# Standard imports
# -----------------------
import sys
import time
import logging
from decimal import Decimal
from tradingview_ta import TA_Handler, Interval
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from nija_coinbase_client import get_usd_balance, place_order_market_quote

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
# PEM load from environment
# -----------------------
pem_content = os.getenv("COINBASE_PEM_CONTENT")
if not pem_content:
    logger.error("[NIJA-BALANCE] Missing COINBASE_PEM_CONTENT in environment")
    sys.exit(1)

try:
    private_key = serialization.load_pem_private_key(
        pem_content.encode(),
        password=None,
        backend=default_backend()
    )
    logger.info("[NIJA-BALANCE] PEM loaded successfully ✅")
except Exception as e:
    logger.error(f"[NIJA-BALANCE] Failed to load PEM: {e}")
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

        if equity < MIN_USD:
            logger.warning("[NIJA] USD balance too low to trade.")
            return None

        if rsi < 30 and close < vwap:
            pct = min(MAX_PCT, 0.05)
            return "buy", pct
        elif rsi > 70 and close > vwap:
            pct = min(MAX_PCT, 0.05)
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
