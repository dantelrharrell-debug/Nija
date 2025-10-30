import time
import logging
from decimal import Decimal
from nija_client import client, get_usd_balance
from tradingview_ta import TA_Handler, Interval

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("nija_worker")

# --- Risk management ---
MIN_PCT = 0.02  # minimum 2% of equity
MAX_PCT = 0.10  # maximum 10% of equity
MIN_USD = 1.0   # minimum trade in USD

# --- Calculate trade size ---
def calculate_order_size(equity: Decimal, pct: float) -> Decimal:
    size = equity * Decimal(pct)
    if size < MIN_USD:
        size = Decimal(MIN_USD)
    return size

# --- Live trading logic ---
def decide_trade():
    """
    Live trade signal using VWAP + RSI from TradingView.
    Returns (side, position_pct) or None.
    """
    try:
        handler = TA_Handler(
            symbol="BTCUSD",
            screener="crypto",
            exchange="COINBASE",
            interval=Interval.INTERVAL_1_MINUTE  # super fast updates for mobile
        )
        analysis = handler.get_analysis()
        rsi = analysis.indicators.get("RSI", 50)
        vwap = analysis.indicators.get("VWAP", 0)
        close = analysis.indicators.get("close", 0)

        equity = get_usd_balance(client)

        # Aggressive but safe signals
        if rsi < 30 and close < vwap:
            pct = min(MAX_PCT, 0.05)  # buy 5% equity
            return "buy", pct
        elif rsi > 70 and close > vwap:
            pct = min(MAX_PCT, 0.05)  # sell 5% equity
            return "sell", pct
        return None
    except Exception as e:
        logger.error(f"[NIJA] decide_trade error: {e}")
        return None

# --- Execute live order ---
def place_order(trade_type: str, position_pct: float):
    equity = get_usd_balance(client)
    order_size = calculate_order_size(equity, position_pct)
    logger.info(f"[NIJA] Executing {trade_type.upper()} order: ${order_size:.2f} ({position_pct*100:.1f}% equity)")

    try:
        order = client.place_order(
            product_id="BTC-USD",
            side=trade_type,
            order_type="market",
            funds=str(order_size)
        )
        logger.info(f"[NIJA] Order confirmed: {order}")
    except Exception as e:
        logger.error(f"[NIJA] Order failed: {e}")

# --- Worker loop ---
def run_worker():
    logger.info("[NIJA] Starting live trading worker (mobile-ready)...")
    while True:
        try:
            trade_signal = decide_trade()
            if trade_signal:
                trade_type, pct = trade_signal
                place_order(trade_type, pct)
            else:
                logger.info("[NIJA] No trade signal. Waiting...")
            time.sleep(5)  # super-fast loop for mobile responsiveness
        except KeyboardInterrupt:
            logger.info("[NIJA] Worker stopped by user")
            break
        except Exception as e:
            logger.error(f"[NIJA] Unexpected error: {e}")
            time.sleep(2)

if __name__ == "__main__":
    run_worker()
