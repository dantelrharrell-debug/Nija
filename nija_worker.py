import time
import logging
from decimal import Decimal
import pandas as pd
from nija_client import client, get_usd_balance
from tradingview_ta import TA_Handler, Interval, Exchange  # if you use TradingView TA

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("nija_worker")

# --- Position sizing ---
MIN_PCT = 0.02  # 2%
MAX_PCT = 0.1   # 10%
MIN_USD = 1.0   # minimum USD per trade

# --- Calculate order size ---
def calculate_order_size(equity: Decimal, pct: float):
    size = equity * Decimal(pct)
    if size < MIN_USD:
        size = Decimal(MIN_USD)
    return size

# --- Trading logic ---
def decide_trade():
    """
    Example live crypto strategy using VWAP + RSI on BTC-USD.
    Returns a trade signal: (side, position_pct)
    """
    try:
        # Use TradingView TA for live indicators
        handler = TA_Handler(
            symbol="BTCUSD",
            screener="crypto",
            exchange="COINBASE",
            interval=Interval.INTERVAL_5_MINUTES
        )
        analysis = handler.get_analysis()
        rsi = analysis.indicators["RSI"]
        vwap = analysis.indicators["VWAP"]
        close_price = analysis.indicators["close"]

        equity = get_usd_balance(client)

        # Aggressive but safe allocation
        if rsi < 30 and close_price < vwap:
            pct = min(MAX_PCT, 0.05)  # 5% of equity
            return "buy", pct
        elif rsi > 70 and close_price > vwap:
            pct = min(MAX_PCT, 0.05)
            return "sell", pct
        else:
            return None
    except Exception as e:
        logger.error(f"[NIJA] decide_trade error: {e}")
        return None

# --- Place order ---
def place_order(trade_type: str, position_pct: float):
    equity = get_usd_balance(client)
    order_size = calculate_order_size(equity, position_pct)
    logger.info(f"[NIJA] Placing {trade_type.upper()} order for ${order_size:.2f} ({position_pct*100:.1f}% of equity)")

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
            trade_signal = decide_trade()
            if trade_signal:
                trade_type, pct = trade_signal
                place_order(trade_type, pct)
            else:
                logger.info("[NIJA] No trade signal. Waiting...")
            time.sleep(10)  # adjust interval for speed
        except KeyboardInterrupt:
            logger.info("[NIJA] Worker stopped by user")
            break
        except Exception as e:
            logger.error(f"[NIJA] Unexpected error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_worker()
