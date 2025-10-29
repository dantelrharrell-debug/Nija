# nija_client.py
"""
Ready-to-paste Coinbase client wrapper for Nija trading bot.

Behavior:
- Tries to instantiate a real Coinbase client if available and environment variables indicate live trading.
- Falls back to DummyClient for safe dry-run behavior (no real API calls).
- Exposes: client, get_accounts, place_order, cancel_order, check_live_status, DRY_RUN
"""

from __future__ import annotations
import os
import logging
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

# Control flags from environment
DRY_RUN = os.getenv("DRY_RUN", "True").lower() not in ("0", "false", "no", "f")
LIVE_TRADING = os.getenv("LIVE_TRADING", "0") in ("1", "true", "yes")

# Optional Coinbase credentials (if using live mode)
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_PASSPHRASE = os.getenv("COINBASE_PASSPHRASE")

# --- Attempt to import a real Coinbase client from common places ---
CoinbaseClient = None
_real_client_module_name = None
try:
    # First try the most-common import we expected
    from coinbase_advanced_py.client import CoinbaseClient  # type: ignore
    _real_client_module_name = "coinbase_advanced_py.client"
    logger.info("[NIJA] Imported CoinbaseClient from coinbase_advanced_py.client")
except Exception:
    try:
        # Some packaging versions might expose a top-level class
        from coinbase_advanced_py import CoinbaseClient  # type: ignore
        _real_client_module_name = "coinbase_advanced_py"
        logger.info("[NIJA] Imported CoinbaseClient from coinbase_advanced_py")
    except Exception:
        CoinbaseClient = None
        logger.warning("[NIJA] coinbase_advanced_py client not found; will use DummyClient")

# --- Dummy client for dry-run / dev / CI safety ---
class DummyClient:
    def __init__(self):
        self.is_dummy = True
        self.is_live = False

    # mimic account list
    def get_accounts(self) -> List[Dict[str, Any]]:
        logger.info("[NIJA-DUMMY] get_accounts called")
        # small example response that wsgi expects
        return [{"currency": "USD", "balance": "1000"}]

    def place_order(self, *args, **kwargs) -> Dict[str, Any]:
        logger.info("[NIJA-DUMMY] place_order called (dummy). args=%s kwargs=%s", args, kwargs)
        # return a structure consistent with a thin wrapper
        return {"id": "dummy-order", "status": "created", "simulated": True, "args": args, "kwargs": kwargs}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        logger.info("[NIJA-DUMMY] cancel_order called (dummy). order_id=%s", order_id)
        return {"id": order_id, "status": "canceled", "simulated": True}

    def get_order(self, order_id: str) -> Dict[str, Any]:
        logger.info("[NIJA-DUMMY] get_order called (dummy). order_id=%s", order_id)
        return {"id": order_id, "status": "created", "simulated": True}

# --- Wrapper to use real client safely if available ---
class WrappedCoinbaseClient:
    def __init__(self, inner):
        self._inner = inner
        self.is_dummy = False
        self.is_live = True

    def get_accounts(self) -> List[Dict[str, Any]]:
        # real client's interface may differ — try common methods, fall back gracefully
        try:
            if hasattr(self._inner, "get_accounts"):
                return self._inner.get_accounts()
            # some clients expose 'accounts' property or method - adapt if needed
            if hasattr(self._inner, "accounts"):
                return self._inner.accounts()
            raise AttributeError("No get_accounts/accounts method on Coinbase client")
        except Exception as e:
            logger.exception("[NIJA] Error calling real client.get_accounts: %s", e)
            raise

    def place_order(self, *args, **kwargs) -> Dict[str, Any]:
        try:
            # Some client libs use place_order(**kwargs)
            if hasattr(self._inner, "place_order"):
                resp = self._inner.place_order(*args, **kwargs)
                # If response is not dict-like, wrap minimally
                return resp if isinstance(resp, dict) else {"result": resp}
            # fallback: attempt order creation via generic 'create_order' or 'new_order'
            for candidate in ("create_order", "new_order", "order_create"):
                if hasattr(self._inner, candidate):
                    fn = getattr(self._inner, candidate)
                    resp = fn(*args, **kwargs)
                    return resp if isinstance(resp, dict) else {"result": resp}
            raise AttributeError("No order method found on real Coinbase client")
        except Exception as e:
            logger.exception("[NIJA] Error placing real order: %s", e)
            raise

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        try:
            if hasattr(self._inner, "cancel_order"):
                return self._inner.cancel_order(order_id)
            if hasattr(self._inner, "cancel"):
                return self._inner.cancel(order_id)
            raise AttributeError("No cancel_order/cancel on real Coinbase client")
        except Exception as e:
            logger.exception("[NIJA] Error cancelling real order: %s", e)
            raise

    def get_order(self, order_id: str) -> Dict[str, Any]:
        try:
            if hasattr(self._inner, "get_order"):
                return self._inner.get_order(order_id)
            if hasattr(self._inner, "order"):
                return self._inner.order(order_id)
            raise AttributeError("No get_order/order method on real Coinbase client")
        except Exception as e:
            logger.exception("[NIJA] Error fetching real order: %s", e)
            raise

# --- Instantiate the appropriate client ---
client = None  # will hold either WrappedCoinbaseClient or DummyClient

if CoinbaseClient and LIVE_TRADING and COINBASE_API_KEY and COINBASE_API_SECRET:
    try:
        # Attempt to instantiate real client with common parameter names.
        # Adapt to expected constructor signature; if your installed client needs different args, adjust here.
        try:
            # common newer library constructor (key, secret, passphrase, sandbox bool)
            real = CoinbaseClient(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET, passphrase=COINBASE_PASSPHRASE)
        except TypeError:
            # fallback to positional constructor
            real = CoinbaseClient(COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_PASSPHRASE)
        client = WrappedCoinbaseClient(real)
        logger.info("[NIJA] CoinbaseClient initialized (LIVE mode).")
    except Exception as e:
        logger.exception("[NIJA] Failed to initialize real CoinbaseClient; falling back to DummyClient. %s", e)
        client = DummyClient()
else:
    # If not configured for live trading, explicitly use dummy
    client = DummyClient()
    if not LIVE_TRADING:
        logger.warning("[NIJA] Falling back to DummyClient (safe). Set LIVE_TRADING=1 and provide API keys to enable real trading.")
    elif not (COINBASE_API_KEY and COINBASE_API_SECRET):
        logger.warning("[NIJA] LIVE_TRADING requested but Coinbase keys missing; using DummyClient.")

# Convenience API expected by wsgi.py
def get_accounts() -> List[Dict[str, Any]]:
    """
    Return account-like list. Wraps client.get_accounts.
    """
    try:
        return client.get_accounts()
    except Exception as e:
        logger.exception("[NIJA] get_accounts error: %s", e)
        # Return a safe structure for health endpoints
        return [{"error": str(e)}]

def place_order(*, side: str, product_id: str, size: str, price: Optional[str] = None, order_type: str = "limit", **extra) -> Dict[str, Any]:
    """
    Place an order through the real client or simulate with DummyClient.
    Returns a dict. If simulated, includes 'simulated': True.
    """
    try:
        # If DRY_RUN or client is dummy, make a simulated response
        if DRY_RUN or getattr(client, "is_dummy", False):
            logger.info("[NIJA] DRY_RUN is set to True or using DummyClient — returning simulated order")
            resp = client.place_order(product_id=product_id, side=side, size=size, price=price, order_type=order_type, **extra)
            # ensure simulated flag present
            if isinstance(resp, dict):
                resp.setdefault("simulated", True)
            return resp

        # Live mode: call real client wrapper
        resp = client.place_order(product_id=product_id, side=side, size=size, price=price, order_type=order_type, **extra)
        # ensure simulated flag is explicitly False if not present
        if isinstance(resp, dict):
            resp.setdefault("simulated", False)
        return resp
    except Exception as e:
        logger.exception("[NIJA] place_order error: %s", e)
        # On error, return a dictionary describing the failure
        return {"error": str(e), "simulated": getattr(client, "is_dummy", True) or DRY_RUN}

def cancel_order(order_id: str) -> Dict[str, Any]:
    try:
        if DRY_RUN or getattr(client, "is_dummy", False):
            logger.info("[NIJA] DRY_RUN/Dummy cancel_order")
            return client.cancel_order(order_id)
        return client.cancel_order(order_id)
    except Exception as e:
        logger.exception("[NIJA] cancel_order error: %s", e)
        return {"error": str(e)}

def get_order(order_id: str) -> Dict[str, Any]:
    try:
        return client.get_order(order_id)
    except Exception as e:
        logger.exception("[NIJA] get_order error: %s", e)
        return {"error": str(e)}

def check_live_status() -> bool:
    """
    Return True if the system is running in real-live mode (i.e., using a real client and DRY_RUN==False).
    """
    try:
        return (not DRY_RUN) and (not getattr(client, "is_dummy", True)) and getattr(client, "is_live", False)
    except Exception:
        return False

# Module-level summary log for startup clarity
logger.info("[NIJA] Module loaded. DRY_RUN=%s LIVE_TRADING=%s client_is_dummy=%s",
            DRY_RUN, LIVE_TRADING, getattr(client, "is_dummy", True))
