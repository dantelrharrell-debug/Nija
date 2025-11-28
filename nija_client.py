# nija_client.py
import os
import logging
import threading
import time

# ----------------------------
# Logging setup
# ----------------------------
LOG = logging.getLogger("nija.client")
LOG.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
handler.setFormatter(formatter)
if not LOG.handlers:
    LOG.addHandler(handler)

# ----------------------------
# Coinbase client import
# ----------------------------
try:
    from coinbase_advanced.client import Client
    COINBASE_IMPORTED = True
except ModuleNotFoundError:
    LOG.warning("coinbase_advanced module not installed. Live trading disabled.")
    Client = None
    COINBASE_IMPORTED = False

# ----------------------------
# Coinbase availability check
# ----------------------------
def coinbase_available() -> bool:
    """Return True if Coinbase client is usable."""
    if not COINBASE_IMPORTED or Client is None:
        return False
    if not os.getenv("COINBASE_API_KEY") or not os.getenv("COINBASE_API_SECRET"):
        LOG.warning("Coinbase environment variables missing.")
        return False
    return True

# ----------------------------
# Connection test
# ----------------------------
def test_coinbase_connection() -> bool:
    """Quick, safe connection test."""
    if not coinbase_available():
        LOG.error("Coinbase client unavailable. Skipping connection test.")
        return False
    try:
        client = Client(
            api_key=os.getenv("COINBASE_API_KEY"),
            api_secret=os.getenv("COINBASE_API_SECRET"),
            api_sub=os.getenv("COINBASE_API_SUB", None)
        )
        client.get_accounts()  # Replace with real method if different
        LOG.info("✅ Coinbase connection successful!")
        return True
    except Exception as e:
        LOG.exception("❌ Coinbase connection failed: %s", e)
        return False

# ----------------------------
# Trading loop management
# ----------------------------
_trading_thread = None
_trading_thread_lock = threading.Lock()

def background_trading_loop():
    """Background trading loop (replace with your strategy)."""
    LOG.info("Trading loop thread started. LIVE_TRADING=%s", os.getenv("LIVE_TRADING", "0"))
    if not coinbase_available() or os.getenv("LIVE_TRADING", "0") != "1":
        LOG.info("Trading loop exiting: conditions not met.")
        return

    client = Client(
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET"),
        api_sub=os.getenv("COINBASE_API_SUB", None)
    )

    try:
        while True:
            LOG.debug("Trading loop heartbeat: check markets, evaluate signals.")
            time.sleep(5)  # Adjust interval for strategy
    except Exception as e:
        LOG.exception("Trading loop crashed: %s", e)

def start_trading_loop() -> bool:
    """Start background trading thread if not already running."""
    global _trading_thread
    with _trading_thread_lock:
        if _trading_thread and _trading_thread.is_alive():
            LOG.info("Trading thread already running (thread id: %s).", _trading_thread.ident)
            return True

        if not coinbase_available():
            LOG.warning("Not starting trading thread: Coinbase unavailable.")
            return False
        if os.getenv("LIVE_TRADING", "0") != "1":
            LOG.warning("LIVE_TRADING != 1. Trading thread not started.")
            return False

        _trading_thread = threading.Thread(target=background_trading_loop, daemon=True, name="nija-trader")
        _trading_thread.start()
        LOG.info("Started trading thread.")
        return True

# ----------------------------
# Optional auto-start
# ----------------------------
try:
    if coinbase_available() and os.getenv("LIVE_TRADING", "0") == "1":
        LOG.info("Auto-starting trading loop (conditions met).")
        start_trading_loop()
except Exception:
    LOG.exception("Auto-start logic raised an exception.")
