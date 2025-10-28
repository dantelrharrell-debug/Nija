"""
nija_client.py

Drop-in Coinbase client wrapper for Nija bot.

Behavior:
- If COINBASE_API_KEY + COINBASE_API_SECRET present AND coinbase_advanced_py is importable,
  initialize real CoinbaseClient.
- Otherwise, use a safe StubCoinbaseClient (no network side-effects) and log a warning.

Provides:
- client: top-level object used by rest of app
- minimal interface: get_accounts(), get_account(account_id), place_order(...),
  get_account_by_currency(code), get_product_ticker(product_id)

This file is intentionally defensive and readable so you can restore the working
deployment state (stub client warning), then add keys safely later.
"""

from __future__ import annotations
import os
import time
import logging
import json
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("nija_client")

COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE")  # optional depending on provider
COINBASE_SANDBOX = os.environ.get("COINBASE_SANDBOX", "false").lower() in ("1", "true", "yes")

# --- Minimal safe stub client -------------------------------------------------
class StubCoinbaseClient:
    """
    Safety-first stub client. Mimics the small subset of the real client's
    interface needed by Nija bot. No network calls, returns deterministic
    minimal structures so the bot can run in DRY_RUN or without keys.
    """
    def __init__(self):
        self._accounts = [
            # Example account entries the rest of app may expect
            {"id": "stub-usd", "currency": "USD", "balance": "1000.00", "available": "1000.00"},
            {"id": "stub-btc", "currency": "BTC", "balance": "0.0000", "available": "0.0000"},
        ]
        logger.warning("Using stub Coinbase client. Set COINBASE_API_KEY + COINBASE_API_SECRET for real trading.")

    def get_accounts(self) -> List[Dict[str, Any]]:
        logger.debug("StubClient.get_accounts called")
        # return copies so callers cannot mutate internal state accidentally
        return [dict(a) for a in self._accounts]

    def get_account(self, account_id: str) -> Dict[str, Any]:
        logger.debug("StubClient.get_account(%s) called", account_id)
        for a in self._accounts:
            if a["id"] == account_id or a["currency"].upper() == account_id.upper():
                return dict(a)
        raise KeyError(f"Stub account not found: {account_id}")

    def get_account_by_currency(self, currency_code: str) -> Optional[Dict[str, Any]]:
        logger.debug("StubClient.get_account_by_currency(%s) called", currency_code)
        for a in self._accounts:
            if a["currency"].upper() == currency_code.upper():
                return dict(a)
        return None

    def place_order(self, *, product_id: str, side: str, funds: Union[str, float, Decimal], **kwargs) -> Dict[str, Any]:
        """
        Simulate placing an order. Returns an order-like structure but does nothing.
        Keep structure minimal and easy to inspect.
        """
        logger.info("StubClient.place_order called: product=%s side=%s funds=%s extra=%s", product_id, side, funds, kwargs)
        # Return a fake order object
        return {
            "id": "stub-order-" + str(int(time.time())),
            "product_id": product_id,
            "side": side,
            "status": "stub",
            "filled_size": "0",
            "executed_value": "0",
            "funds": str(funds),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def get_product_ticker(self, product_id: str) -> Dict[str, Any]:
        logger.debug("StubClient.get_product_ticker(%s) called", product_id)
        # Minimal ticker fields
        return {"product_id": product_id, "price": "0.00", "bid": "0.00", "ask": "0.00"}

    def close(self):
        logger.debug("StubClient.close called")

# --- Real client loader ------------------------------------------------------
def _init_real_client():
    """
    Attempt to instantiate the real Coinbase client. If import fails or keys missing,
    raise an exception so caller can fallback to stub.
    """
    try:
        # coinbase_advanced_py exposes a client; adapt as necessary if your dependency differs
        from coinbase_advanced_py.client import CoinbaseClient  # type: ignore
    except Exception as e:
        logger.exception("Failed to import coinbase_advanced_py (real Coinbase client not available): %s", e)
        raise

    if not COINBASE_API_KEY or not COINBASE_API_SECRET:
        raise ValueError("Missing COINBASE_API_KEY/COINBASE_API_SECRET")

    # Many Coinbase wrappers allow a sandbox flag or base_url override. Check your package docs.
    kwargs = {}
    if COINBASE_SANDBOX:
        kwargs["sandbox"] = True

    try:
        client = CoinbaseClient(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET, api_passphrase=COINBASE_PASSPHRASE, **kwargs)
        logger.info("Real CoinbaseClient initialized (sandbox=%s)", COINBASE_SANDBOX)
        return client
    except Exception as e:
        logger.exception("Failed to initialize real CoinbaseClient: %s", e)
        raise

# --- Helper wrappers (abstracting stub vs real client) -----------------------
class NijaClientWrapper:
    def __init__(self, raw_client: Any, is_stub: bool = False):
        self.raw = raw_client
        self.is_stub = is_stub

    def get_accounts(self) -> List[Dict[str, Any]]:
        try:
            if self.is_stub:
                return self.raw.get_accounts()
            # real client might return generator/objects - normalize to list of dicts
            accounts = self.raw.get_accounts()
            # if it's a requests-like response or object list, carefully convert
            if isinstance(accounts, (list, tuple)):
                return [self._normalize_account(a) for a in accounts]
            # fallback - try to iterate
            return [self._normalize_account(a) for a in accounts]
        except Exception:
            logger.exception("Error fetching accounts from client; returning []")
            return []

    def _normalize_account(self, a: Any) -> Dict[str, Any]:
        # Try to be tolerant of different client return shapes
        if isinstance(a, dict):
            return a
        # For object-like responses, attempt to read attributes
        try:
            return {
                "id": getattr(a, "id", None) or getattr(a, "account_id", None) or str(a),
                "currency": getattr(a, "currency", None) or getattr(a, "currency_code", None),
                "balance": str(getattr(a, "balance", None) or getattr(a, "available", None) or "0"),
            }
        except Exception:
            return {"id": str(a), "currency": None, "balance": "0"}

    def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        try:
            if self.is_stub:
                return self.raw.get_account(account_id)
            # many clients provide get_account or get_account_by_id
            if hasattr(self.raw, "get_account"):
                a = self.raw.get_account(account_id)
                return self._normalize_account(a)
            # fallback: fetch all and match
            accounts = self.get_accounts()
            for acc in accounts:
                if acc.get("id") == account_id or acc.get("currency", "").upper() == account_id.upper():
                    return acc
            return None
        except Exception:
            logger.exception("Error in get_account(%s)", account_id)
            return None

    def get_account_by_currency(self, currency_code: str) -> Optional[Dict[str, Any]]:
        try:
            if self.is_stub:
                return self.raw.get_account_by_currency(currency_code)
            # fallback loop
            accounts = self.get_accounts()
            for acc in accounts:
                if acc.get("currency", "").upper() == currency_code.upper():
                    return acc
            return None
        except Exception:
            logger.exception("Error in get_account_by_currency(%s)", currency_code)
            return None

    def place_order(self, product_id: str, side: str, funds: Union[str, float, Decimal], **kwargs) -> Dict[str, Any]:
        """
        Unified place_order wrapper. Attempts the call and returns a safe dict.
        On failure returns a dict with 'error' key (so caller can inspect).
        """
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                if self.is_stub:
                    return self.raw.place_order(product_id=product_id, side=side, funds=funds, **kwargs)
                # Try common APIs
                if hasattr(self.raw, "place_order"):
                    order = self.raw.place_order(product_id=product_id, side=side, funds=str(funds), **kwargs)
                    # Normalize
                    if isinstance(order, dict):
                        return order
                    # If object-like, try to convert
                    return json.loads(json.dumps(order, default=lambda o: getattr(o, "__dict__", str(o))))
                elif hasattr(self.raw, "create_order"):
                    order = self.raw.create_order(product_id=product_id, side=side, funds=str(funds), **kwargs)
                    if isinstance(order, dict):
                        return order
                    return json.loads(json.dumps(order, default=lambda o: getattr(o, "__dict__", str(o))))
                else:
                    raise RuntimeError("Underlying client has no place_order/create_order method")
            except Exception:
                logger.exception("Attempt %d/%d failed to place order %s %s %s", attempt, max_attempts, product_id, side, funds)
                if attempt < max_attempts:
                    time.sleep(0.5)
                else:
                    return {"error": "order_failed", "product": product_id, "side": side, "funds": str(funds)}
        # fallback
        return {"error": "unknown"}

    def get_product_ticker(self, product_id: str) -> Dict[str, Any]:
        try:
            if self.is_stub:
                return self.raw.get_product_ticker(product_id)
            if hasattr(self.raw, "get_product_ticker"):
                return self.raw.get_product_ticker(product_id)
            # try public_products or market data endpoints
            if hasattr(self.raw, "get_ticker"):
                return self.raw.get_ticker(product_id)
            return {"product_id": product_id, "price": None, "bid": None, "ask": None}
        except Exception:
            logger.exception("Error getting product ticker for %s", product_id)
            return {"product_id": product_id, "price": None, "bid": None, "ask": None}

    def close(self):
        try:
            if hasattr(self.raw, "close"):
                self.raw.close()
        except Exception:
            logger.exception("Error closing underlying client")

# --- Initialize client -------------------------------------------------------
def _build_client() -> NijaClientWrapper:
    # Prefer real client if keys present
    if COINBASE_API_KEY and COINBASE_API_SECRET:
        try:
            real = _init_real_client()
            return NijaClientWrapper(real, is_stub=False)
        except Exception:
            logger.warning("Falling back to stub Coinbase client due to initialization error.")
            return NijaClientWrapper(StubCoinbaseClient(), is_stub=True)
    else:
        # No keys provided — use stub and log same style message as your working logs
        return NijaClientWrapper(StubCoinbaseClient(), is_stub=True)

# The client object expected by the rest of the application
client = _build_client()

# --- Small quick-selftest function (safe) -----------------------------------
def _self_test():
    """
    Quick safe test when module loaded. Non-destructive; uses stub when keys missing.
    Logs a summary similar to your earlier successful boot logs.
    """
    try:
        accounts = client.get_accounts()
        if accounts:
            logger.info("nija_client self-test: found %d accounts (first: %s)", len(accounts), accounts[0].get("currency"))
        else:
            logger.info("nija_client self-test: no accounts returned")
    except Exception:
        logger.exception("nija_client self-test failed")

# Run lightweight self-test when imported (keeps behavior similar to prior logs)
_self_test()
