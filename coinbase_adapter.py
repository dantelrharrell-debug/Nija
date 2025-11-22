"""
Light adapter that detects and normalizes common Coinbase client libraries.

Expose a small, stable API:
- get_accounts()
- get_open_orders()
- get_fills(product_id=None)
- place_market_order(product_id, side, size)

This adapter is defensive and will return safe defaults if no client is available.
"""
import os
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("coinbase_adapter")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


class Adapter:
    def __init__(self, client: Any, client_name: str):
        self.client = client
        self.client_name = client_name
        logger.info(f"coinbase_adapter: using client {client_name}")

    # Generic call helper
    def _call(self, *fn_names, default=None, **kwargs):
        for name in fn_names:
            try:
                if not self.client:
                    continue
                if not hasattr(self.client, name):
                    continue
                fn = getattr(self.client, name)
                if callable(fn):
                    # Try kwargs, then positional fallback
                    try:
                        return fn(**kwargs) if kwargs else fn()
                    except TypeError:
                        try:
                            return fn(*kwargs.values()) if kwargs else fn()
                        except Exception as e:
                            logger.debug(f"{self.client_name}.{name} positional call failed: {e}")
                            continue
            except Exception as e:
                logger.debug(f"{self.client_name}.{name} raised: {e}")
                continue
        return default

    def get_accounts(self) -> List[Dict[str, Any]]:
        try:
            res = self._call("get_accounts", "list_accounts", "list_wallets", "accounts", "fetch_accounts", default=[])
            if res is None:
                return []
            if isinstance(res, dict) and "accounts" in res:
                return res.get("accounts") or []
            if isinstance(res, list):
                return res
            try:
                return list(res)
            except Exception:
                return []
        except Exception as e:
            logger.error(f"Adapter.get_accounts error: {e}")
            return []

    def get_open_orders(self) -> List[Dict[str, Any]]:
        try:
            res = self._call("get_orders", "list_orders", "get_open_orders", "orders", "fetch_open_orders", default=[])
            if res is None:
                return []
            if isinstance(res, dict) and "orders" in res:
                return res.get("orders") or []
            if isinstance(res, list):
                return res
            try:
                return list(res)
            except Exception:
                return []
        except Exception as e:
            logger.error(f"Adapter.get_open_orders error: {e}")
            return []

    def get_fills(self, product_id: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            if product_id:
                res = self._call("get_fills", "list_fills", "fetch_fills", default=[], product_id=product_id)
            else:
                res = self._call("get_fills", "list_fills", "fetch_fills", "fills", default=[])
            if res is None:
                return []
            if isinstance(res, dict) and "fills" in res:
                return res.get("fills") or []
            if isinstance(res, list):
                return res
            try:
                return list(res)
            except Exception:
                return []
        except Exception as e:
            logger.error(f"Adapter.get_fills error: {e}")
            return []

    def place_market_order(self, product_id: str, side: str, size: float) -> Optional[Dict[str, Any]]:
        try:
            payload = {"product_id": product_id, "side": side, "size": str(size), "type": "market"}

            # Try common single-dict APIs
            res = self._call("create_order", "place_order", "order", default=None, order=payload)
            if res is not None:
                return res

            # cbpro-style market order
            res = self._call("place_market_order", "market_order", default=None, product_id=product_id, side=side, size=str(size))
            if res is not None:
                return res

            # positional signature fallback
            for name in ("create_order", "place_order", "order"):
                if hasattr(self.client, name):
                    try:
                        fn = getattr(self.client, name)
                        return fn(product_id, side, str(size))
                    except Exception:
                        try:
                            return fn(product_id, side, size)
                        except Exception:
                            continue

            logger.error("Adapter.place_market_order: no supported order method found")
            return None
        except Exception as e:
            logger.error(f"Adapter.place_market_order exception: {e}")
            return None


def create_adapter(api_key: Optional[str], api_secret: Optional[str], passphrase: Optional[str], pem: Optional[str], org_id: Optional[str], base_url: Optional[str] = None) -> Adapter:
    # Try coinbase_advanced if available (guarded)
    try:
        from coinbase_advanced.client import Client as AdvancedClient  # type: ignore
        try:
            client = AdvancedClient(api_key=api_key, api_secret=api_secret, pem=pem, org_id=org_id, base_url=base_url)
            return Adapter(client, "coinbase_advanced.Client")
        except Exception as e:
            logger.debug(f"coinbase_advanced init failed: {e}")
    except Exception:
        pass

    # Try official coinbase wallet client
    try:
        from coinbase.wallet.client import Client as WalletClient  # type: ignore
        try:
            client = WalletClient(api_key=api_key, api_secret=api_secret)
            return Adapter(client, "coinbase.wallet.client.Client")
        except Exception as e:
            logger.debug(f"coinbase.wallet.client init failed: {e}")
    except Exception:
        pass

    # Try top-level coinbase client
    try:
        from coinbase.client import Client as CoinbaseClientLib  # type: ignore
        try:
            client = CoinbaseClientLib(api_key=api_key, api_secret=api_secret)
            return Adapter(client, "coinbase.client.Client")
        except Exception as e:
            logger.debug(f"coinbase.client init failed: {e}")
    except Exception:
        pass

    # Try cbpro
    try:
        import cbpro  # type: ignore
        try:
            p = passphrase or os.getenv("COINBASE_API_PASSPHRASE", "")
            client = cbpro.AuthenticatedClient(api_key, api_secret, p)
            return Adapter(client, "cbpro.AuthenticatedClient")
        except Exception as e:
            logger.debug(f"cbpro init failed: {e}")
    except Exception:
        pass

    logger.info("create_adapter: no supported Coinbase client library found; returning adapter with client=None")
    return Adapter(None, "none")
