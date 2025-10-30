import os
import sys
import time
import logging
from decimal import Decimal
from tradingview_ta import TA_Handler, Interval

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("nija_live")

# --- Coinbase client setup ---
try:
    from coinbase.rest import RESTClient
    logger.info("[NIJA] RESTClient imported successfully")
except Exception as e:
    logger.error(f"[NIJA] Could not import RESTClient: {e}")
    sys.exit(1)

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = None  # Not used / optional

if not API_KEY or not API_SECRET:
    logger.error("[NIJA] Missing API_KEY or API_SECRET. Cannot start live trading.")
    sys.exit(1)

# --- Initialize Coinbase REST client ---
try:
    client = RESTClient(api_key=API_KEY, api_secret=API_SECRET)
    accounts = client.get_accounts()
    usd_balance = next((Decimal(a["balance"]) for a in accounts if a["currency"] == "USD"), None)
    if usd_balance is None:
        raise Exception("No USD account found")
    logger.info(f"[NIJA] Coinbase auth OK. USD balance: {usd_balance}")
except Exception as e:
    logger.error(f"[NIJA] Coinbase authentication failed: {e}")
    sys.exit(1)

# --- Risk management ---
MIN_PCT = 0.02
MAX_PCT = 0.10
MIN_USD = 1.0

def get_usd_balance():
    try:
        accounts = client.get_accounts()
        for acc in accounts:
            if acc.get("currency") == "USD":
                return Decimal(acc.get("balance", "0"))
    except Exception as e:
        logger.warning(f"[NIJA] Could not fetch USD balance: {e}")
    return Decimal("0")

def calculate_order_size(equity: Decimal, pct: float) -> Decimal:
    size = equity * Decimal(pct)
    return max(size, Decimal(MIN_USD))

# --- Trading logic ---
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

        equity = get_usd_balance()

        if rsi < 30 and close < vwap:
            return "buy", min(MAX_PCT, 0.05)
        elif rsi > 70 and close > vwap:
            return "sell", min(MAX_PCT, 0.05)
        return None
    except Exception as e:
        logger.error(f"[NIJA] decide_trade error: {e}")
        return None

# --- Place order ---
def place_order(trade_type: str, position_pct: float):
    equity = get_usd_balance()
    order_size = calculate_order_size(equity, position_pct)
    logger.info(f"[NIJA] Executing {trade_type.upper()} order: ${order_size:.2f}")

    try:
        order = client.place_order(
            product_id="BTC-USD",
            side=trade_type,
            order_type="market",
            funds=str(order_size)
        )
        logger.info(f"[NIJA] Order executed: {order}")
    except Exception as e:
        logger.error(f"[NIJA] Order failed: {e}")

# --- Worker loop ---
def run_worker():
    logger.info("[NIJA] Starting live trading worker...")
    while True:
        try:
            signal = decide_trade()
            if signal:
                trade_type, pct = signal
                place_order(trade_type, pct)
            else:
                logger.info("[NIJA] No trade signal. Waiting...")
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("[NIJA] Worker stopped by user")
            break
        except Exception as e:
            logger.error(f"[NIJA] Unexpected error in worker: {e}")
            time.sleep(2)

# --- Start live trading ---
if __name__ == "__main__":
    run_worker()
