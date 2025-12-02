# bot/live_bot_script.py
"""
Safe Coinbase integration and exported "app hooks" for the web startup.

This module:
 - imports the official coinbase package when available
 - provides create_coinbase_client() that returns a Client or None
 - exposes start_trading_loop(), stop_trading_loop(), status_info(), get_account_info()
 - guards against missing env vars or missing package so imports never crash
 - logs clearly so you can trace what's happening at container start
"""

from __future__ import annotations
import os
import logging
import threading
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Console handler if not already configured by app
if not logger.handlers:
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    logger.addHandler(ch)

# Try to import official coinbase package (safe to fail)
_coinbase_available = False
Client = None
try:
    # official coinbase SDK client for wallet endpoints
    from coinbase.wallet.client import Client  # type: ignore
    _coinbase_available = True
    logger.info("Official 'coinbase' package imported successfully.")
except Exception as e:
    logger.warning("Official 'coinbase' package not available. Live trading disabled. (%s)", e)

# Runtime control for trading loop
_trading_thread: Optional[threading.Thread] = None
_trading_thread_stop_event = threading.Event()


def create_coinbase_client() -> Optional["Client"]:
    """
    Create and return a coinbase.wallet.client.Client or None if missing credentials/package.
    The `coinbase` official client uses API key + secret for simple wallet operations.
    If you rely on Coinbase Pro (Exchange) or other APIs, adapt accordingly.
    """
    if not _coinbase_available:
        logger.warning("create_coinbase_client: coinbase package not installed.")
        return None

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    # Some codepaths use passphrase (Coinbase Pro); accept it but client may not require it.
    api_passphrase = os.environ.get("COINBASE_API_PASSPHRASE", "")

    if not api_key or not api_secret:
        logger.warning(
            "create_coinbase_client: COINBASE_API_KEY or COINBASE_API_SECRET missing. "
            "Returning None (sandbox/dummy)."
        )
        return None

    try:
        client = Client(api_key=api_key, api_secret=api_secret)  # type: ignore[arg-type]
        # No guaranteed call here — keep light to avoid network blocking at import time.
        logger.info("Coinbase Client created (credentials present).")
        return client
    except Exception as exc:
        logger.exception("Failed to create Coinbase Client: %s", exc)
        return None


def get_account_info() -> Dict[str, Any]:
    """
    Retrieve simple account info. Returns a dict describing whether a client exists and basic info.
    Does not raise if coinbase is missing.
    """
    client = create_coinbase_client()
    if client is None:
        return {"ok": False, "reason": "no_client", "live_trading": bool(os.environ.get("LIVE_TRADING"))}

    try:
        # Example: list accounts (this will perform a network call)
        accounts = client.get_accounts(limit=5)  # keep small to avoid long waits
        acct_summary = []
        for acct in accounts.data:
            acct_summary.append({"id": getattr(acct, "id", None), "balance": getattr(acct, "balance", None)})
        return {"ok": True, "accounts": acct_summary}
    except Exception as exc:
        logger.exception("get_account_info: error talking to Coinbase: %s", exc)
        return {"ok": False, "reason": "api_error", "error": str(exc)}


def _trading_loop_dummy(interval: float = 5.0):
    """
    Example placeholder trading loop. Replace with your real trading logic.
    This function checks env LIVE_TRADING to decide behavior.
    """
    logger.info("Trading loop started (dummy). LIVE_TRADING=%s", os.environ.get("LIVE_TRADING"))
    try:
        while not _trading_thread_stop_event.is_set():
            live_flag = bool(os.environ.get("LIVE_TRADING"))
            logger.debug("Trading loop tick. live=%s", live_flag)
            # Example: pull a tiny bit of account info to keep it realistic
            try:
                client = create_coinbase_client()
                if client:
                    # lightweight call (limit small)
                    _ = client.get_accounts(limit=1)
                    logger.debug("Checked accounts successfully.")
            except Exception as exc:
                logger.warning("Trading loop account check failed: %s", exc)

            # TODO: put your trading decision / order placement code here.
            # Example placeholder: log a heartbeat and sleep.
            logger.info("Trading loop heartbeat — replace with your strategy.")
            # Respect interval but allow fast stop
            for _ in range(int(interval * 10)):
                if _trading_thread_stop_event.is_set():
                    break
                time.sleep(interval / (interval * 10))
    finally:
        logger.info("Trading loop stopped.")


def start_trading_loop(interval: float = 5.0) -> bool:
    """
    Public function to start the trading loop in a background thread.
    Returns True if started or already running, False on failure.
    """
    global _trading_thread, _trading_thread_stop_event

    if _trading_thread and _trading_thread.is_alive():
        logger.info("start_trading_loop called but trading loop already running.")
        return True

    if not _coinbase_available and bool(os.environ.get("LIVE_TRADING")):
        logger.warning("LIVE_TRADING requested but 'coinbase' package not available. Not starting.")
        return False

    _trading_thread_stop_event.clear()
    _trading_thread = threading.Thread(target=_trading_loop_dummy, args=(interval,), name="nija-trading-loop", daemon=True)
    _trading_thread.start()
    logger.info("Trading thread started (interval=%s seconds).", interval)
    return True


def stop_trading_loop(timeout: float = 5.0) -> bool:
    """
    Signal the trading loop to stop and join the thread.
    Returns True if successfully stopped or not running.
    """
    global _trading_thread, _trading_thread_stop_event
    if not _trading_thread:
        logger.info("stop_trading_loop called but no trading thread exists.")
        return True

    logger.info("Stopping trading loop...")
    _trading_thread_stop_event.set()
    _trading_thread.join(timeout)
    if _trading_thread.is_alive():
        logger.warning("Trading thread did not exit within timeout.")
        return False

    _trading_thread = None
    logger.info("Trading loop stopped cleanly.")
    return True


def status_info() -> Dict[str, Any]:
    """
    Return lightweight status used by your web app when importing this module.
    Avoid heavy network calls — keep it fast at import/startup.
    """
    client_present = _coinbase_available and bool(os.environ.get("COINBASE_API_KEY"))
    live_trading = bool(os.environ.get("LIVE_TRADING"))
    running = bool(_trading_thread and _trading_thread.is_alive())
    return {
        "coinbase_installed": _coinbase_available,
        "client_present": client_present,
        "live_trading_env": live_trading,
        "trading_loop_running": running,
    }


# Expose a friendly CLI-style sanity check when run as a script
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Simple sanity checks for bot.live_bot_script")
    parser.add_argument("--status", action="store_true", help="Print status_info")
    parser.add_argument("--start", action="store_true", help="Start the dummy trading loop (foreground)")
    parser.add_argument("--account", action="store_true", help="Fetch simple account info (may call network)")
    args = parser.parse_args()

    if args.status:
        import json
        print(json.dumps(status_info(), indent=2))
    elif args.account:
        info = get_account_info()
        import json
        print(json.dumps(info, indent=2))
    elif args.start:
        logger.info("Starting dummy trading loop in foreground. Ctrl-C to exit.")
        try:
            _trading_thread_stop_event.clear()
            _trading_loop_dummy(interval=5.0)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received, stopping.")
            _trading_thread_stop_event.set()
    else:
        parser.print_help()


# symbols other modules expect to import
__all__ = [
    "create_coinbase_client",
    "get_account_info",
    "start_trading_loop",
    "stop_trading_loop",
    "status_info",
]
