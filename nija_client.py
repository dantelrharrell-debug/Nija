# nija_client.py
"""
Final robust Nija Coinbase client wrapper.
- Exposes `client` with methods: get_accounts(), place_order(...)
- Exposes flags: client.is_live (True when real client instantiated & live trading enabled)
                 client.is_dummy (True when DummyClient is used)
- place_order returns {"id": ..., "status": ..., "simulated": bool, "raw": ...}
"""

import os
import logging
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Env config ---
ENV = os.environ
API_KEY = ENV.get("COINBASE_API_KEY") or ENV.get("CB_API_KEY")
API_SECRET = ENV.get("COINBASE_API_SECRET") or ENV.get("CB_API_SECRET")
API_PASSPHRASE = ENV.get("COINBASE_API_PASSPHRASE") or ENV.get("CB_PASSPHRASE")
SANDBOX = ENV.get("SANDBOX", "False").lower() in ("1", "true", "yes")
LIVE_TRADING_FLAG = ENV.get("LIVE_TRADING", "0").lower() in ("1", "true", "yes")

# Safe default: require explicit LIVE_TRADING=1 + keys for live
DRY_RUN = not (LIVE_TRADING_FLAG and API_KEY and API_SECRET)

# --- Try importing coinbase client (multiples) ---
CoinbaseImpl = None
try:
    from coinbase_advanced_py.client import CoinbaseClient  # type: ignore
    CoinbaseImpl = CoinbaseClient
    logger.info("[NIJA] Found coinbase_advanced_py.client.CoinbaseClient")
except Exception:
    try:
        from coinbase_advanced_py import CoinbaseClient  # type: ignore
        CoinbaseImpl = CoinbaseClient
        logger.info("[NIJA] Found coinbase_advanced_py.CoinbaseClient")
    except Exception:
        try:
            from coinbase_advanced_py import RESTClient  # type: ignore
            CoinbaseImpl = RESTClient
            logger.info("[NIJA] Found coinbase_advanced_py.RESTClient")
        except Exception:
            try:
                from coinbase_advanced_py.client import RESTClient  # type: ignore
                CoinbaseImpl = RESTClient
                logger.info("[NIJA] Found coinbase_advanced_py.client.RESTClient")
            except Exception:
                logger.warning("[NIJA] coinbase_advanced_py client not found; will use DummyClient")

# --- Instantiate helper ---
def _instantiate_impl(impl_class):
    candidates = [
        {"api_key": API_KEY, "api_secret": API_SECRET, "api_passphrase": API_PASSPHRASE, "sandbox": SANDBOX},
        {"key": API_KEY, "secret": API_SECRET, "passphrase": API_PASSPHRASE, "sandbox": SANDBOX},
        {"api_key": API_KEY, "api_secret": API_SECRET, "passphrase": API_PASSPHRASE},
        {"api_key": API_KEY, "api_secret": API_SECRET},
    ]
    last_exc = None
    for kw in candidates:
        # skip if keys missing for constructor that requires them
        if ("api_key" in kw or "key" in kw) and not (API_KEY and API_SECRET):
            continue
        try:
            inst = impl_class(**{k: v for k, v in kw.items() if v is not None})
            logger.info(f"[NIJA] Instantiated client with args: {list(kw.keys())}")
            return inst
        except Exception as e:
            last_exc = e
            logger.debug(f"[NIJA] constructor attempt failed: {e}")
    # try no-arg
    try:
        inst = impl_class()
        logger.info("[NIJA] Instantiated client with no-arg constructor (env-driven)")
        return inst
    except Exception as e:
        last_exc = e
    raise last_exc or RuntimeError("Failed to instantiate coinbase client")

# --- Adapter / Normalizer ---
class CoinbaseAdapter:
    def __init__(self, raw_client: Any, is_live: bool = False, is_dummy: bool = False):
        self._raw = raw_client
        self.is_live = bool(is_live)
        self.is_dummy = bool(is_dummy)

    def get_accounts(self) -> List[Dict[str, Any]]:
        # try common method names
        for name in ("get_accounts", "accounts", "list_accounts", "list_accounts_sync", "get_account_list"):
            if hasattr(self._raw, name):
                try:
                    fn = getattr(self._raw, name)
                    raw = fn() if callable(fn) else fn
                    return self._normalize_accounts(raw)
                except Exception as e:
                    logger.exception(f"[NIJA] Error calling {name}(): {e}")

        # fallback: return minimal
        logger.warning("[NIJA] No accounts method found on client; returning fallback account")
        return [{"currency": "USD", "balance": "0"}]

    def place_order(self, side: str, product_id: str, size: str, price: Optional[str] = None, order_type: str = "market") -> Dict[str, Any]:
        """
        Returns dict: {id, status, simulated (bool), raw}
        """
        # Respect DRY_RUN: simulate if adapter not live or DRY_RUN set globally
        if not getattr(self, "is_live", False) or DRY_RUN:
            simulated = True
            fake_id = f"sim-{int(time.time())}"
            resp = {"id": fake_id, "status": "simulated", "simulated": True, "raw": {"side": side, "product_id": product_id, "size": size, "price": price, "type": order_type}}
            logger.info(f"[NIJA-DUMMY] Simulated order: {resp}")
            return resp

        # try common order methods
        payloads = []
        if order_type == "market":
            payloads = [
                {"side": side, "product_id": product_id, "size": size, "type": "market"},
                {"side": side, "product_id": product_id, "quantity": size, "type": "market"},
            ]
        else:
            payloads = [
                {"side": side, "product_id": product_id, "size": size, "price": price, "type": "limit"},
                {"side": side, "product_id": product_id, "quantity": size, "price": price, "type": "limit"},
            ]

        methods = ("place_order", "create_order", "order_create", "create_trade")
        last_exc = None
        for m in methods:
            if hasattr(self._raw, m):
                fn = getattr(self._raw, m)
                for p in payloads:
                    try:
                        resp = fn(**{k: v for k, v in p.items() if v is not None})
                        return {"id": resp.get("id") if isinstance(resp, dict) else getattr(resp, "id", None),
                                "status": resp.get("status") if isinstance(resp, dict) else getattr(resp, "status", None),
                                "simulated": False, "raw": resp}
                    except TypeError:
                        try:
                            resp = fn(p)
                            return {"id": resp.get("id") if isinstance(resp, dict) else getattr(resp, "id", None),
                                    "status": resp.get("status") if isinstance(resp, dict) else getattr(resp, "status", None),
                                    "simulated": False, "raw": resp}
                        except Exception as e:
                            last_exc = e
                    except Exception as e:
                        last_exc = e
                        logger.exception(f"[NIJA] Error calling {m} with payload {p}: {e}")

        # try a generic request wrapper if present
        wrapper = getattr(self._raw, "request", None) or getattr(self._raw, "call_api", None)
        if wrapper:
            for p in payloads:
                try:
                    resp = wrapper("POST", "/orders", json=p)
                    return {"id": resp.get("id") if isinstance(resp, dict) else getattr(resp, "id", None),
                            "status": resp.get("status") if isinstance(resp, dict) else getattr(resp, "status", None),
                            "simulated": False, "raw": resp}
                except Exception as e:
                    last_exc = e
                    logger.debug(f"[NIJA] Generic wrapper failed: {e}")

        raise last_exc or RuntimeError("No order placement method worked on client")

    def _normalize_accounts(self, raw) -> List[Dict[str, Any]]:
        if raw is None:
            return []
        out = []
        try:
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        currency = item.get("currency") or item.get("asset") or item.get("code")
                        balance = item.get("balance") or item.get("available") or item.get("amount")
                        out.append({"currency": currency, "balance": str(balance)})
                    else:
                        currency = getattr(item, "currency", None) or getattr(item, "asset", None)
                        balance = getattr(item, "balance", None) or getattr(item, "available", None)
                        out.append({"currency": currency, "balance": str(balance)})
                return out
            if isinstance(raw, dict):
                currency = raw.get("currency") or raw.get("asset") or raw.get("code")
                balance = raw.get("balance") or raw.get("available") or raw.get("amount")
                return [{"currency": currency, "balance": str(balance)}]
            # iterable
            for item in raw:
                currency = item.get("currency") if isinstance(item, dict) else getattr(item, "currency", None)
                balance = item.get("balance") if isinstance(item, dict) else getattr(item, "balance", None)
                out.append({"currency": currency, "balance": str(balance)})
            return out
        except Exception as e:
            logger.exception(f"[NIJA] Error normalizing accounts: {e}")
            return [{"currency": "UNKNOWN", "balance": "0"}]

# --- Dummy client ---
class DummyClient:
    def __init__(self):
        self._fake_balance = Decimal("1000.00")

    def get_accounts(self):
        logger.info("[NIJA-DUMMY] get_accounts called")
        return [{"currency": "USD", "balance": str(self._fake_balance)}]

    def place_order(self, *args, **kwargs):
        logger.info(f"[NIJA-DUMMY] place_order called (dummy). args={args} kwargs={kwargs}")
        return {"id": "dummy-order", "status": "created", "simulated": True, "raw": {"args": args, "kwargs": kwargs}}

# --- Build final client adapter ---
_adapter: Optional[CoinbaseAdapter] = None

if CoinbaseImpl is not None and API_KEY and API_SECRET and LIVE_TRADING_FLAG:
    try:
        raw_instance = _instantiate_impl(CoinbaseImpl)
        _adapter = CoinbaseAdapter(raw_instance, is_live=True, is_dummy=False)
        if DRY_RUN:
            logger.warning("[NIJA] LIVE client instantiated but DRY_RUN is True. Orders will be simulated.")
        else:
            logger.info("[NIJA] Live Coinbase client ready.")
    except Exception as e:
        logger.exception(f"[NIJA] Failed to instantiate official client: {e}")
        _adapter = None

if _adapter is None:
    logger.warning("[NIJA] Falling back to DummyClient (safe). Set LIVE_TRADING=1 and provide API keys to enable real trading.")
    _adapter = CoinbaseAdapter(DummyClient(), is_live=False, is_dummy=True)
    # enforce DRY_RUN when dummy
    DRY_RUN = True

# Publicly exposed client object
client = _adapter

# Convenience wrappers
def get_accounts() -> List[Dict[str, Any]]:
    try:
        return client.get_accounts()
    except Exception as e:
        logger.exception(f"[NIJA] get_accounts failed: {e}")
        return [{"currency": "USD", "balance": "0"}]

def place_order(side: str, product_id: str, size: str, price: Optional[str] = None, order_type: str = "market") -> Dict[str, Any]:
    try:
        return client.place_order(side=side, product_id=product_id, size=size, price=price, order_type=order_type)
    except Exception as e:
        logger.exception(f"[NIJA] place_order failed: {e}")
        return {"id": None, "status": "failed", "simulated": True, "error": str(e)}

# Sanity-run when executed directly
if __name__ == "__main__":
    logger.info(f"[NIJA] DRY_RUN={DRY_RUN} LIVE_TRADING_FLAG={LIVE_TRADING_FLAG} SANDBOX={SANDBOX}")
    accounts = get_accounts()
    logger.info(f"[NIJA] Accounts: {accounts}")
    order_resp = place_order("buy", "BTC-USD", "0.0001", price=None, order_type="market")
    logger.info(f"[NIJA] Example order response: {order_resp}")
