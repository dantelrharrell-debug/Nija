import os
import sys
import time
import queue
import logging
from threading import Thread
from dotenv import load_dotenv

load_dotenv()

def call_with_timeout(func, args=(), kwargs=None, timeout_seconds=30):
    """
    Execute a function with a timeout. Returns (result, error).
    If timeout occurs, returns (None, TimeoutError).
    Default timeout is 30 seconds to accommodate production API latency.
    """
    if kwargs is None:
        kwargs = {}
    result_queue = queue.Queue()

    def worker():
        try:
            result = func(*args, **kwargs)
            result_queue.put((True, result))
        except Exception as e:
            result_queue.put((False, e))

    t = Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout_seconds)

    if t.is_alive():
        return None, TimeoutError(f"Operation timed out after {timeout_seconds}s")

    try:
        ok, value = result_queue.get_nowait()
        return (value, None) if ok else (None, value)
    except queue.Empty:
        return None, Exception("No result returned from worker")

# Add bot directory to path if running from root
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Optional market price helper; safe fallback if unavailable
try:
    from bot.market_data import get_current_price  # type: ignore
except Exception:
    def get_current_price(symbol: str):
        return None

class TradingStrategy:
    """Coinbase-focused TradingStrategy placeholder.

    This placeholder ensures the bot boots without unintended Alpaca dependency.
    It keeps runtime safe by performing no trades; full APEX v7.1 execution
    is handled by dedicated modules elsewhere in the codebase.
    """

    def __init__(self):
        self.logger = logging.getLogger("nija")
        # Strategy parameters documented here for visibility only
        self.scan_interval_seconds = 150

    def run_cycle(self):
        """Run a single safe, no-op cycle.

        Intended to be replaced by the Coinbase-backed implementation.
        """
        try:
            self.logger.info("Strategy cycle placeholder: Coinbase-only mode active; no Alpaca.")
            # Example read-only check to keep loop active without trades
            price = get_current_price("BTC-USD")
            if price:
                self.logger.info(f"Observed BTC-USD price: {price}")
        except Exception as e:
            # Never raise to avoid crashing the bot loop
            self.logger.warning(f"Strategy cycle placeholder error: {e}")
