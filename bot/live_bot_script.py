cat > bot/live_bot_script.py <<'PY'
# bot/live_bot_script.py
import os
import threading
import time
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from coinbase.wallet.client import Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("live_bot_script")

_coinbase_client: Optional[Client] = None
_trading_thread: Optional[threading.Thread] = None
_thread_stop_event: Optional[threading.Event] = None
_last_health_check: Optional[float] = None

def get_coinbase_client() -> Client:
    global _coinbase_client
    if _coinbase_client is not None:
        return _coinbase_client
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    missing = [n for n, v in (("COINBASE_API_KEY", api_key), ("COINBASE_API_SECRET", api_secret)) if not v]
    if missing:
        raise RuntimeError(f"Missing Coinbase environment variables: {', '.join(missing)}")
    _coinbase_client = Client(api_key, api_secret)
    log.info("Coinbase Client initialized successfully")
    return _coinbase_client

def _trading_loop(stop_event: threading.Event):
    global _last_health_check
    log.info("Trading loop started (placeholder). No live trades will be executed.")
    try:
        client = get_coinbase_client()
    except Exception as e:
        log.exception("Trading loop: cannot init Coinbase client: %s", e)
        return
    iteration = 0
    while not stop_event.is_set():
        iteration += 1
        try:
            if hasattr(client, "get_accounts"):
                _ = client.get_accounts()
            _last_health_check = time.time()
            log.debug("Health check OK iteration %d", iteration)
        except Exception as e:
            log.warning("Health check failed iteration %d: %s", iteration, e)
        stop_event.wait(10)
    log.info("Trading loop exiting.")

def start_trading_loop(daemon: bool = True) -> None:
    global _trading_thread, _thread_stop_event
    if _trading_thread is not None and _trading_thread.is_alive():
        log.info("start_trading_loop: already running.")
        return
    _thread_stop_event = threading.Event()
    _trading_thread = threading.Thread(
        target=_trading_loop, args=(_thread_stop_event,), daemon=daemon, name="live-trading-thread"
    )
    _trading_thread.start()
    log.info("start_trading_loop: thread started (daemon=%s).", daemon)

def stop_trading_loop(timeout: float = 5.0) -> None:
    global _trading_thread, _thread_stop_event
    if _thread_stop_event is None:
        log.info("stop_trading_loop: nothing to stop.")
        return
    _thread_stop_event.set()
    if _trading_thread is not None:
        _trading_thread.join(timeout)
        if _trading_thread.is_alive():
            log.warning("stop_trading_loop: thread did not stop within timeout.")
    _trading_thread = None
    _thread_stop_event = None
    log.info("stop_trading_loop: stopped.")

def status_info() -> Dict[str, Any]:
    client_ok = False
    client_err = None
    try:
        get_coinbase_client()
        client_ok = True
    except Exception as e:
        client_err = str(e)
    thread_status = "none"
    if _trading_thread is not None:
        thread_status = "running" if _trading_thread.is_alive() else "stopped"
    last_hc = None
    if _last_health_check is not None:
        last_hc = datetime.utcfromtimestamp(_last_health_check).isoformat() + "Z"
    missing = [n for n in ("COINBASE_API_KEY", "COINBASE_API_SECRET") if not os.environ.get(n)]
    return {
        "client_ok": client_ok,
        "client_error": client_err,
        "trading_thread": thread_status,
        "last_health_check": last_hc,
        "missing_env": missing,
    }

if __name__ == "__main__":
    print("live_bot_script quick self-check:")
    try:
        print("status:", status_info())
    except Exception as e:
        print("status() raised:", repr(e))
PY
