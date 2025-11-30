# bot/live_bot_script.py
"""
Safe, verbose trading-bot bootstrap for deployments.

Drop this into bot/live_bot_script.py. It provides:
- start_trading_loop() -> starts main loop (blocking)
- stop_trading_loop() -> signals loop to stop
Logs status about coinbase_advanced presence and environment variables.
"""

import os
import time
import logging
from threading import Event

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("bot.live_bot_script")

# Module-level stop event so tests/containers can stop the loop if needed.
stop_event = Event()

# Config from environment with sane defaults
HEARTBEAT_SECONDS = int(os.environ.get("BOT_HEARTBEAT_SECONDS", "60"))
LIVE_TRADING_FLAG = os.environ.get("LIVE_TRADING", "0").strip()  # "1" to enable
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_SUB = os.environ.get("COINBASE_API_SUB")  # optional, if used by your client

# Try to import coinbase_advanced (support a couple common import paths)
cb_module = None
Client = None
try:
    # preferred: coinbase_advanced.client.Client
    from coinbase_advanced.client import Client  # type: ignore
    cb_module = "coinbase_advanced.client"
    logger.info("Imported coinbase_advanced.client.Client")
except Exception:
    try:
        import coinbase_advanced as cb  # type: ignore
        cb_module = "coinbase_advanced"
        # some libs expose different entry points; we'll detect at runtime
        logger.info("Imported coinbase_advanced")
    except Exception:
        logger.error("coinbase_advanced module not installed. Live trading disabled.")
        cb_module = None

def create_coinbase_client():
    """
    Safely create and return a Coinbase client object or None.
    This function does not raise on import errors; it logs and returns None.
    """
    if cb_module is None:
        logger.debug("create_coinbase_client: coinbase_advanced not present.")
        return None

    # Ensure API credentials present
    if not (COINBASE_API_KEY and COINBASE_API_SECRET):
        logger.warning("Coinbase API key/secret not set in env. Skipping client creation.")
        return None

    # Try common Client constructors
    try:
        if Client:
            client = Client(
                api_key=COINBASE_API_KEY,
                api_secret=COINBASE_API_SECRET,
                api_sub=COINBASE_API_SUB,
            )
            logger.info("Coinbase client created using coinbase_advanced.client.Client")
            return client
    except Exception as exc:
        logger.exception("Failed building Client via coinbase_advanced.client.Client: %s", exc)

    # fallback: try coinbase_advanced.Client or coinbase_advanced.connect style
    try:
        import coinbase_advanced as cb  # type: ignore
        # try common shapes:
        if hasattr(cb, "Client"):
            client_cls = getattr(cb, "Client")
            client = client_cls(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET, api_sub=COINBASE_API_SUB)
            logger.info("Coinbase client created using coinbase_advanced.Client fallback")
            return client
        if hasattr(cb, "connect"):
            client = cb.connect(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET, api_sub=COINBASE_API_SUB)
            logger.info("Coinbase client created using coinbase_advanced.connect fallback")
            return client
    except Exception as exc:
        logger.exception("Fallback coinbase client creation failed: %s", exc)

    logger.error("Unable to instantiate a Coinbase client with the available library.")
    return None

def _log_status():
    logger.info("=== BOT STATUS ===")
    logger.info("HEARTBEAT_SECONDS=%s", HEARTBEAT_SECONDS)
    logger.info("LIVE_TRADING env var = %s", LIVE_TRADING_FLAG)
    logger.info("coinbase_advanced present = %s", bool(cb_module))
    logger.info("COINBASE_API_KEY present = %s", bool(COINBASE_API_KEY))
    logger.info("==================")

def start_trading_loop():
    """
    Blocking loop. Intended to be run in a daemon thread if started from Flask:
        threading.Thread(target=start_trading_loop, daemon=True).start()
    The loop:
    - emits a heartbeat every HEARTBEAT_SECONDS
    - attempts to create a coinbase client only when LIVE_TRADING=="1" and package + keys present
    """
    logger.info("start_trading_loop() called")
    _log_status()

    # If user hasn't enabled the bot via env, do a passive heartbeat-only mode.
    if LIVE_TRADING_FLAG != "1":
        logger.warning("LIVE_TRADING != '1' -> running in heartbeat-only (dry-run) mode.")

    # Try to create client here (but only attempt connection if LIVE_TRADING=="1")
    client = None
    if LIVE_TRADING_FLAG == "1":
        client = create_coinbase_client()
        if client:
            logger.info("Coinbase client ready. Bot will attempt live trading actions when implemented.")
        else:
            logger.warning("Live trading requested but client couldn't be created. Staying in dry-run mode.")

    iteration = 0
    try:
        while not stop_event.is_set():
            iteration += 1
            logger.info("bot heartbeat #%d - live_trading=%s - client_present=%s",
                        iteration, LIVE_TRADING_FLAG == "1", client is not None)

            # Place to add safe, read-only checks (e.g., fetch account balances) if client exists.
            # For safety this template DOES NOT place orders automatically.
            if client:
                try:
                    # Example safe read: attempt to call a safe method if it exists.
                    if hasattr(client, "get_accounts"):
                        try:
                            accounts = client.get_accounts()  # may vary by client implementation
                            logger.info("Fetched %d accounts (safe read).", len(accounts) if accounts else 0)
                        except Exception as exc:
                            logger.warning("Safe read (get_accounts) failed: %s", exc)
                    else:
                        logger.debug("Client has no get_accounts method; skipping safe read.")
                except Exception as exc:
                    logger.exception("Unexpected error when interacting with client: %s", exc)

            # Sleep/heartbeat interval (interruptible)
            # Use small slices so stop_event responds quickly when asked to stop
            slept = 0
            while slept < HEARTBEAT_SECONDS and not stop_event.is_set():
                time.sleep(1)
                slept += 1

    except Exception as exc:
        logger.exception("Uncaught exception in trading loop: %s", exc)
    finally:
        logger.info("start_trading_loop() exiting (stop_event=%s)", stop_event.is_set())

def stop_trading_loop():
    """Signal the background loop to stop."""
    stop_event.set()
    logger.info("stop_trading_loop() called — stop_event set.")

# Expose a friendly boolean helper for web diagnostic endpoint
def status_info():
    return {
        "live_trading_env": LIVE_TRADING_FLAG,
        "coinbase_module_installed": bool(cb_module),
        "api_key_present": bool(COINBASE_API_KEY),
        "api_secret_present": bool(COINBASE_API_SECRET),
        "heartbeat_seconds": HEARTBEAT_SECONDS,
        "loop_running": not stop_event.is_set()
    }

# If module imported directly for quick local test (not executed in Gunicorn workers):
if __name__ == "__main__":
    # simple local run for dev: starts loop in main thread (Ctrl-C to stop)
    logger.info("Starting local blocking trading loop (CTRL-C to stop).")
    try:
        start_trading_loop()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received. Stopping loop.")
        stop_trading_loop()
