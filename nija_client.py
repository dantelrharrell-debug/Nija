# nija_client.py
import logging
import os
import threading
import time

LOG = logging.getLogger("nija.client")
LOG.setLevel(logging.INFO)

# Try to import the Coinbase advanced client. If it's not present, remain safe.
try:
    # If you installed the official library or your fork, adjust import as needed.
    from coinbase_advanced.client import Client
    COINBASE_IMPORTED = True
except Exception as e:
    LOG.warning("coinbase_advanced import failed: %s", e)
    Client = None
    COINBASE_IMPORTED = False

def coinbase_available() -> bool:
    """Return True if Coinbase client is usable."""
    if not COINBASE_IMPORTED or Client is None:
        return False
    # Also check required env vars
    if not os.getenv("COINBASE_API_KEY") or not os.getenv("COINBASE_API_SECRET"):
        LOG.warning("Coinbase env vars missing.")
        return False
    return True

def test_coinbase_connection():
    """Simple single-shot connection test (non-throwing)."""
    if not coinbase_available():
        LOG.error("Coinbase client not available for test.")
        return False
    try:
        client = Client(
            api_key=os.getenv("COINBASE_API_KEY"),
            api_secret=os.getenv("COINBASE_API_SECRET"),
            api_sub=os.getenv("COINBASE_API_SUB", None)
        )
        # Replace with a real test method for the client you have.
        info = getattr(client, "get_account", lambda: None)()
        LOG.info("Coinbase test connection OK (quick check).")
        return True
    except Exception as e:
        LOG.exception("Coinbase connection test failed: %s", e)
        return False

# Trading loop control
_trading_thread = None
_trading_thread_lock = threading.Lock()

def background_trading_loop():
    """Example background trading loop — replace strategy with your real logic."""
    LOG.info("Trading loop thread started. LIVE_TRADING=%s", os.getenv("LIVE_TRADING", "0"))
    try:
        if not coinbase_available() or os.getenv("LIVE_TRADING", "0") != "1":
            LOG.info("Trading loop exiting: coinbase_available=%s live_flag=%s",
                     coinbase_available(), os.getenv("LIVE_TRADING", "0"))
            return
        # Create client once per thread (safe)
        client = Client(
            api_key=os.getenv("COINBASE_API_KEY"),
            api_secret=os.getenv("COINBASE_API_SECRET"),
            api_sub=os.getenv("COINBASE_API_SUB", None)
        )
        # Dummy loop: replace with your real strategy loop
        while True:
            # Example: check account, market, evaluate signals, place orders...
            LOG.info("Trading loop heart-beat: would poll markets and maybe place orders.")
            # Sleep interval should be tuned to your strategy (seconds)
            time.sleep(5)
    except Exception as e:
        LOG.exception("Trading loop crashed: %s", e)

def start_trading_loop():
    """Start background trading worker if not already running."""
    global _trading_thread
    with _trading_thread_lock:
        if _trading_thread and _trading_thread.is_alive():
            LOG.info("Trading thread already running (pid-like thread id: %s).", _trading_thread.ident)
            return True
        # Only start if coinbase is available and LIVE_TRADING=1
        if not coinbase_available():
            LOG.warning("Not starting trading thread because coinbase is not available.")
            return False
        if os.getenv("LIVE_TRADING", "0") != "1":
            LOG.warning("LIVE_TRADING != 1, not starting trading thread.")
            return False
        _trading_thread = threading.Thread(target=background_trading_loop, daemon=True, name="nija-trader")
        _trading_thread.start()
        LOG.info("Started trading thread.")
        return True

# Optional: start automatically on import if conditions met (safe)
try:
    if coinbase_available() and os.getenv("LIVE_TRADING", "0") == "1":
        LOG.info("Auto-starting trading loop (conditions met).")
        start_trading_loop()
except Exception:
    LOG.exception("Auto-start logic raised an exception.")
