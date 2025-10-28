# nija_client.py
"""
Drop-in nija_client with start_trading/stop_trading exports and safe stub fallback.
Overwrite the existing file in your repo with this file (via GitHub or Render web editor).
"""

from __future__ import annotations
import os
import time
import threading
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union, Callable

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("nija_client")

COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE")
COINBASE_SANDBOX = os.environ.get("COINBASE_SANDBOX", "false").lower() in ("1", "true", "yes")


# ---------- Safe stub client ----------
class StubCoinbaseClient:
    def __init__(self):
        self._accounts = [
            {"id": "stub-usd", "currency": "USD", "balance": "1000.00", "available": "1000.00"},
            {"id": "stub-btc", "currency": "BTC", "balance": "0.0000", "available": "0.0000"},
        ]
        logger.warning("Using stub Coinbase client. Set COINBASE_API_KEY + COINBASE_API_SECRET for real trading.")

    def get_accounts(self) -> List[Dict[str, Any]]:
        return [dict(a) for a in self._accounts]

    def get_account(self, account_id: str) -> Dict[str, Any]:
        for a in self._accounts:
            if a["id"] == account_id or a["currency"].upper() == account_id.upper():
                return dict(a)
        raise KeyError(f"Stub account not found: {account_id}")

    def get_account_by_currency(self, currency_code: str) -> Optional[Dict[str, Any]]:
        for a in self._accounts:
            if a["currency"].upper() == currency_code.upper():
                return dict(a)
        return None

    def place_order(self, *, product_id: str, side: str, funds: Union[str, float, Decimal], **kwargs) -> Dict[str, Any]:
        logger.info("StubClient.place_order called: %s %s %s", product_id, side, funds)
        return {
            "id": "stub-order-" + str(int(time.time())),
            "product_id": product_id,
            "side": side,
            "status": "stub",
            "funds": str(funds),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def get_product_ticker(self, product_id: str) -> Dict[str, Any]:
        return {"product_id": product_id, "price": "0.00", "bid": "0.00", "ask": "0.00"}

    def close(self):
        logger.debug("StubClient.close")


# ---------- Real client discovery (best-effort) ----------
def _discover_and_init_real_client():
    """
    Try to import/instantiate a real client from coinbase_advanced_py.
    If it fails, raise ImportError so caller falls back to stub.
    """
    try:
        # common layout attempt
        from coinbase_advanced_py.client import CoinbaseClient  # type: ignore
        return CoinbaseClient(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET,
                              api_passphrase=COINBASE_API_PASSPHRASE, sandbox=COINBASE_SANDBOX)
    except Exception:
        logger.debug("Pattern 1 failed for coinbase_advanced_py.client")

    try:
        import coinbase_advanced_py as cap  # type: ignore
        if hasattr(cap, "CoinbaseClient"):
            return getattr(cap, "CoinbaseClient")(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET,
                                                   api_passphrase=COINBASE_API_PASSPHRASE, sandbox=COINBASE_SANDBOX)
    except Exception:
        logger.debug("Pattern 2 failed for coinbase_advanced_py top-level")

    raise ImportError("Could not locate CoinbaseClient in coinbase_advanced_py")


# ---------- Wrapper ----------
class NijaClientWrapper:
    def __init__(self, raw: Any, is_stub: bool):
        self.raw = raw
        self.is_stub = is_stub

    def get_accounts(self) -> List[Dict[str, Any]]:
        try:
            if self.is_stub:
                return self.raw.get_accounts()
            accounts = self.raw.get_accounts()
            return [a if isinstance(a, dict) else {"id": getattr(a, "id", str(a)),
                                                  "currency": getattr(a, "currency", None),
                                                  "balance": str(getattr(a, "balance", "0"))}
                    for a in accounts]
        except Exception:
            logger.exception("Error get_accounts")
            return []

    def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        try:
            if self.is_stub:
                return self.raw.get_account(account_id)
            if hasattr(self.raw, "get_account"):
                a = self.raw.get_account(account_id)
                return a if isinstance(a, dict) else {"id": getattr(a, "id", str(a)),
                                                     "currency": getattr(a, "currency", None),
                                                     "balance": str(getattr(a, "balance", "0"))}
            for acc in self.get_accounts():
                if acc.get("id") == account_id or acc.get("currency", "").upper() == account_id.upper():
                    return acc
        except Exception:
            logger.exception("Error get_account")
        return None

    def place_order(self, product_id: str, side: str, funds: Union[str, float, Decimal], **kwargs) -> Dict[str, Any]:
        try:
            if self.is_stub:
                return self.raw.place_order(product_id=product_id, side=side, funds=funds, **kwargs)
            if hasattr(self.raw, "place_order"):
                return self.raw.place_order(product_id=product_id, side=side, funds=str(funds), **kwargs)
            if hasattr(self.raw, "create_order"):
                return self.raw.create_order(product_id=product_id, side=side, funds=str(funds), **kwargs)
        except Exception:
            logger.exception("place_order failed")
        return {"error": "order_failed", "product": product_id}

    def get_product_ticker(self, product_id: str) -> Dict[str, Any]:
        try:
            if self.is_stub:
                return self.raw.get_product_ticker(product_id)
            if hasattr(self.raw, "get_product_ticker"):
                return self.raw.get_product_ticker(product_id)
            if hasattr(self.raw, "get_ticker"):
                return self.raw.get_ticker(product_id)
        except Exception:
            logger.exception("get_product_ticker failed")
        return {"product_id": product_id, "price": None}

    def close(self):
        try:
            if hasattr(self.raw, "close"):
                self.raw.close()
        except Exception:
            logger.exception("close failed")


# ---------- Build client ----------
def _build_client() -> NijaClientWrapper:
    if COINBASE_API_KEY and COINBASE_API_SECRET:
        try:
            real = _discover_and_init_real_client()
            logger.info("Real Coinbase client initialized (sandbox=%s)", COINBASE_SANDBOX)
            return NijaClientWrapper(real, is_stub=False)
        except Exception as e:
            logger.error("Real client init failed: %s", e)
            logger.warning("Falling back to stub client")
            return NijaClientWrapper(StubCoinbaseClient(), is_stub=True)
    else:
        return NijaClientWrapper(StubCoinbaseClient(), is_stub=True)


client = _build_client()


# ---------- Trading thread control (EXPORTED) ----------
_trading_thread: Optional[threading.Thread] = None
_trading_stop_event = threading.Event()
_trading_lock = threading.Lock()


def _default_loop(poll_interval: float = 2.0):
    logger.info("🔥 Trading loop starting (pid=%s) 🔥", os.getpid())
    while not _trading_stop_event.is_set():
        try:
            accounts = client.get_accounts()
            logger.debug("Default loop accounts: %s", [a.get("currency") for a in accounts])
            ticker = client.get_product_ticker("BTC-USD")
            logger.debug("BTC-USD ticker: %s", ticker.get("price"))
        except Exception:
            logger.exception("Error in default loop")
        _trading_stop_event.wait(poll_interval)
    logger.info("Trading loop exiting")


def start_trading(trading_fn: Optional[Callable[[], None]] = None, poll_interval: float = 2.0) -> threading.Thread:
    """Start trading thread; exported so nija_live_snapshot can import it."""
    global _trading_thread
    with _trading_lock:
        if _trading_thread and _trading_thread.is_alive():
            logger.info("Trading thread already running")
            return _trading_thread

        _trading_stop_event.clear()

        def runner():
            try:
                if trading_fn:
                    logger.info("Custom trading_fn runner started")
                    while not _trading_stop_event.is_set():
                        try:
                            trading_fn()
                        except Exception:
                            logger.exception("Error in trading_fn")
                        _trading_stop_event.wait(poll_interval)
                else:
                    _default_loop(poll_interval=poll_interval)
            finally:
                logger.info("Trading runner exiting")

        _trading_thread = threading.Thread(target=runner, name="nija-trading-loop", daemon=False)
        _trading_thread.start()
        logger.info("Trading loop thread started")
        return _trading_thread


def stop_trading(timeout: Optional[float] = 5.0):
    _trading_stop_event.set()
    global _trading_thread
    if _trading_thread:
        _trading_thread.join(timeout)
        if _trading_thread.is_alive():
            logger.warning("Trading thread did not stop in time")
        else:
            logger.info("Trading thread stopped")
        _trading_thread = None


# ---------- Self-test ----------
def _self_test():
    try:
        accs = client.get_accounts()
        logger.info("nija_client self-test: %d accounts (first: %s)", len(accs), accs[0].get("currency") if accs else None)
    except Exception:
        logger.exception("self-test failed")


_self_test()
