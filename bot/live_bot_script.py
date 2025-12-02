# bot/live_bot_script.py
import os
import threading
import time
import logging
from typing import Optional

# Official Coinbase SDK import (required)
from coinbase.wallet.client import Client

# Configure logging (Gunicorn will also capture these)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("live_bot_script")

# Module-level singletons
_coinbase_client: Optional[Client] = None
_trading_thread: Optional[threading.Thread] = None
_thread_stop_event: Optional[threading.Event] = None


def get_coinbase_client() -> Client:
    """
    Initialize and return a Coinbase Client using environment variables.
    Raises RuntimeError if required env vars missing.
    """
    global _coinbase_client
    if _coinbase_client is not None:
        return _coinbase_client

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    # note: official SDK may not require passphrase; keep it if you need it elsewhere
    api_pass = os.environ.get("COINBASE_API_PASSPHRASE", None)

    missing = [name for name, val in [
        ("COINBASE_API_KEY", api_key),
        ("COINBASE_API_SECRET", api_secret)
    ] if not val]

    if missing:
        raise RuntimeError(f"Missing Coinbase environment variables: {', '.join(missing)}")

    # Initialize official Client
    _coinbase_client = Client(api_key, api_secret)
    log.info("Coinbase Client initialized successfully")
    return _coinbase_client


def _trading_loop(stop_event: threading.Event):
    """
    Safe placeholder trading loop. Replace with your real trading logic.
    Runs until stop_event is set.
    """
    log.info("Trading loop started (placeholder). No live trades will be executed.")
    try:
        client = get_coinbase_client()
    except Exception as e:
        log.exception("Failed to initialize Coinbase client inside trading loop: %s", e)
        return

    iteration = 0
    while not stop_event.is_set():
        iteration += 1
        # Lightweight health check example: try to fetch accounts (non-destructive)
        try:
            # NOTE: smaller calls to confirm connectivity; adjust to your SDK usage
            accounts = client.get_accounts() if hasattr(client, "get_accounts") else None
            log.debug("Health check iteration %d: accounts=%s", iteration, "ok" if accounts is not None else "n/a")
        except Exception as e:
            log.warning("Health check iteration %d raised: %s", iteration, e)

        # Sleep between checks; keeps loop low impact
        stop_event.wait(10)

    log.info("Trading loop exiting cleanly.")


def start_trading_loop(daemon: bool = True) -> None:
    """
    Public function required by app import. Starts a single background thread.
    Calling multiple times is idempotent (won't spawn duplicates).
    """
    global _trading_thread, _thread_stop_event

    if _trading_thread is not None and _trading_thread.is_alive():
        log.info("Trading loop already running (pid thread alive).")
        return

    _thread_stop_event = threading.Event()
    _trading_thread = threading.Thread(target=_trading_loop, args=(_thread_stop_event,), daemon=daemon, name="live-trading-thread")
    _trading_thread.start()
    log.info("start_trading_loop: background thread started (daemon=%s).", daemon)


def stop_trading_loop(timeout: float = 5.0) -> None:
    """
    Signal background thread to stop and optionally wait for it.
    """
    global _trading_thread, _thread_stop_event
    if _thread_stop_event is None:
        log.info("stop_trading_loop: no thread to stop.")
        return
    _thread_stop_event.set()
    if _trading_thread is not None:
        _trading_thread.join(timeout)
        if _trading_thread.is_alive():
            log.warning("stop_trading_loop: thread did not exit within timeout.")
    _trading_thread = None
    _thread_stop_event = None
    log.info("stop_trading_loop: stopped.")


# If other modules import start_trading_loop at import time, they can call it safely.
# No auto-start here; your web.wsgi or entrypoint should call start_trading_loop() when you want to run.
