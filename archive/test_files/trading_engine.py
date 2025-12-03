# trading_engine.py
import os
import logging
import time
import threading
from typing import Optional, Dict, Any

from startup import check_coinbase_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("trading_engine")

# Try to import your existing strategy file if present.
# Create a file nija_strategy.py with required hooks (see notes below)
try:
    import nija_strategy as strategy
    logger.info("Loaded nija_strategy module.")
except Exception as e:
    strategy = None
    logger.warning(f"nija_strategy not found or failed to import: {e}. Running in dry mode.")

# Start connection (this will exit if credentials missing/invalid)
client = check_coinbase_connection(require_live=True)

# Simple in-memory position store (replace with DB for production)
POSITIONS: Dict[str, Dict[str, Any]] = {}  # key by symbol

# Example helper: place order (adjust to coinbase_advanced method names)
def place_market_order(symbol: str, side: str, size: float, product_type: str = "spot") -> Dict:
    """
    side: "buy" or "sell"
    size: notional or quantity depending on product
    product_type: "spot", "futures", "options" (your client must support)
    """
    logger.info(f"Placing market order: {side} {size} {symbol} ({product_type})")
    try:
        # You must adapt this block to the actual client method signatures.
        # Below is a pseudo-call; replace with real calls.
        if product_type == "spot":
            resp = client.create_spot_order(product_id=symbol, side=side, size=size, order_type="market")
        elif product_type == "futures":
            resp = client.create_futures_order(symbol=symbol, side=side, size=size, type="market")
        else:
            resp = client.create_order(symbol=symbol, side=side, size=size)  # fallback
        logger.info(f"Order response: {resp}")
        return resp
    except Exception as e:
        logger.error(f"Order failed: {e}")
        raise

def set_trailing_stop(symbol: str, entry_price: float, trailing_pct: float, position_id: str):
    """
    Maintain trailing stop in our POSITIONS dict.
    trailing_pct: e.g. 0.02 for 2% trailing stop
    """
    POSITIONS[symbol]["trailing"] = {
        "enabled": True,
        "trail_pct": trailing_pct,
        "entry_price": entry_price,
        "stop_price": entry_price * (1 - trailing_pct) if POSITIONS[symbol]["side"] == "buy" else entry_price * (1 + trailing_pct)
    }
    logger.info(f"Set trailing stop for {symbol}: {POSITIONS[symbol]['trailing']}")

def set_trailing_takeprofit(symbol: str, entry_price: float, takeprofit_pct: float):
    POSITIONS[symbol]["takeprofit"] = {
        "enabled": True,
        "tp_pct": takeprofit_pct,
        "tp_price": entry_price * (1 + takeprofit_pct) if POSITIONS[symbol]["side"] == "buy" else entry_price * (1 - takeprofit_pct)
    }
    logger.info(f"Set trailing takeprofit for {symbol}: {POSITIONS[symbol]['takeprofit']}")

def monitor_positions(loop_interval: float = 5.0):
    """
    Poll market price and update trailing stop / TP.
    """
    logger.info("Position monitor started.")
    while True:
        try:
            for symbol, pos in list(POSITIONS.items()):
                # get current price - adapt to client method
                try:
                    ticker = client.get_ticker(symbol)  # adapt method name
                    price = float(ticker["price"] if isinstance(ticker, dict) and "price" in ticker else getattr(ticker, "price", None))
                except Exception:
                    logger.debug(f"Could not fetch ticker for {symbol}; skipping.")
                    continue

                # handle trailing stop
                trailing = pos.get("trailing")
                if trailing and trailing.get("enabled"):
                    side = pos["side"]
                    old_stop = trailing["stop_price"]
                    if side == "buy":
                        # if price rises, move stop up
                        new_stop_candidate = price * (1 - trailing["trail_pct"])
                        if new_stop_candidate > old_stop:
                            trailing["stop_price"] = new_stop_candidate
                            logger.info(f"Moved trailing stop up for {symbol} -> {trailing['stop_price']:.8f}")
                        # if price hits stop -> close
                        if price <= trailing["stop_price"]:
                            logger.info(f"Price {price} <= trailing stop {trailing['stop_price']}. Closing position.")
                            close_position(symbol)
                            continue
                    else:  # sell/short
                        new_stop_candidate = price * (1 + trailing["trail_pct"])
                        if new_stop_candidate < old_stop:
                            trailing["stop_price"] = new_stop_candidate
                            logger.info(f"Moved trailing stop down for {symbol} -> {trailing['stop_price']:.8f}")
                        if price >= trailing["stop_price"]:
                            logger.info(f"Price {price} >= trailing stop {trailing['stop_price']}. Closing position.")
                            close_position(symbol)
                            continue

                # handle takeprofit
                tp = pos.get("takeprofit")
                if tp and tp.get("enabled"):
                    if (pos["side"] == "buy" and price >= tp["tp_price"]) or (pos["side"] == "sell" and price <= tp["tp_price"]):
                        logger.info(f"Take profit reached for {symbol} at {price} (TP: {tp['tp_price']}). Closing position.")
                        close_position(symbol)
                        continue
        except Exception as e:
            logger.error(f"Error in position monitor: {e}")
        time.sleep(loop_interval)

def open_position(symbol: str, side: str, size: float, entry_price: Optional[float] = None, product_type: str = "spot", trailing_pct: Optional[float] = None, tp_pct: Optional[float] = None):
    """
    Places order and records position.
    """
    order = place_market_order(symbol=symbol, side=side, size=size, product_type=product_type)
    # Interpret order response to get fill price / id
    filled_price = None
    order_id = None
    try:
        # adapt to response structure
        order_id = order.get("id", getattr(order, "id", None))
        filled_price = float(order.get("filled_price", order.get("price", getattr(order, "price", None)) or entry_price))
    except Exception:
        logger.warning(f"Could not parse order response, using entry_price if provided: {entry_price}")
        filled_price = entry_price

    POSITIONS[symbol] = {
        "order_id": order_id,
        "side": side,
        "size": size,
        "entry_price": filled_price,
        "product_type": product_type
    }
    logger.info(f"Opened position: {symbol} {side} size={size} entry_price={filled_price} id={order_id}")

    if trailing_pct and filled_price:
        set_trailing_stop(symbol, filled_price, trailing_pct, order_id)
    if tp_pct and filled_price:
        set_trailing_takeprofit(symbol, filled_price, tp_pct)

def close_position(symbol: str):
    pos = POSITIONS.get(symbol)
    if not pos:
        logger.warning(f"No position to close for {symbol}")
        return
    side = "sell" if pos["side"] == "buy" else "buy"
    size = pos["size"]
    product_type = pos.get("product_type", "spot")
    try:
        resp = place_market_order(symbol=symbol, side=side, size=size, product_type=product_type)
        logger.info(f"Closed position {symbol}. Close order resp: {resp}")
    except Exception as e:
        logger.error(f"Error closing position {symbol}: {e}")
    finally:
        POSITIONS.pop(symbol, None)

def engine_loop(poll_interval: float = 1.0):
    """
    Main engine: receives signals from strategy and acts.
    The strategy module (nija_strategy.py) should expose a function get_signals()
    that returns a list of signals like:
    [{"symbol":"BTC-USD","side":"buy","size":0.001,"product":"spot","trailing_pct":0.02,"tp_pct":0.05}, ...]
    """
    logger.info("Trading engine starting.")
    # start position monitor in background thread
    monitor_thread = threading.Thread(target=monitor_positions, daemon=True)
    monitor_thread.start()

    while True:
        try:
            signals = []
            if strategy and hasattr(strategy, "get_signals"):
                try:
                    signals = strategy.get_signals()
                except Exception as e:
                    logger.exception(f"Strategy get_signals error: {e}")
            else:
                logger.debug("No strategy.get_signals — engine idle or dry-run.")
            for s in signals:
                sym = s.get("symbol")
                if not sym:
                    continue
                # only open if we don't have a position
                if sym in POSITIONS:
                    logger.info(f"Already have position for {sym}; skipping signal.")
                    continue
                open_position(
                    symbol=sym,
                    side=s.get("side", "buy"),
                    size=s.get("size", 0.0),
                    product_type=s.get("product", "spot"),
                    trailing_pct=s.get("trailing_pct"),
                    tp_pct=s.get("tp_pct")
                )
        except Exception as e:
            logger.error(f"Engine loop error: {e}")
        time.sleep(poll_interval)

if __name__ == "__main__":
    engine_loop()
