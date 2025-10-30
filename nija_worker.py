# nija_worker.py
import time
import logging
from decimal import Decimal
from tradingview_ta import TA_Handler, Interval

from nija_coinbase_client import get_usd_balance, place_order_market_quote

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nija_worker")

# Risk parameters (adjust as desired)
MIN_PCT = 0.02
MAX_PCT = 0.10
MIN_USD = Decimal("1.00")

def calculate_order_size(equity: Decimal, pct: float) -> Decimal:
    size = equity * Decimal(str(pct))
    if size < MIN_USD:
        size = MIN_USD
    return size.quantize(Decimal("0.01"))  # cents resolution

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
    order_size = calculate_order_size(equity, position_pct)  # USD amount
    logger.info(f"[NIJA] Executing {trade_type.upper()} order: ${order_size} ({position_pct*100:.1f}% equity)")
    try:
        # place market order using quote_size (amount in USD)
        response = place_order_market_quote(product_id="BTC-USD", side=("BUY" if trade_type=="buy" else "SELL"), quote_size=str(order_size))
        logger.info("[NIJA] Order response: %s", response)
    except Exception as e:
        logger.error("[NIJA] Order failed: %s", e)

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
            time.sleep(5)
        except KeyboardInterrupt:
            logger.info("[NIJA] Worker stopped by user")
            break
        except Exception as e:
            logger.error("[NIJA] Unexpected error in worker: %s", e)
            time.sleep(2)

if __name__ == "__main__":
    run_worker()
