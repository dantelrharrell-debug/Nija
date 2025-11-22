"""
Robust, defensive CoinbaseClient wrapper for Nija bot.

Features:
- Tries multiple installed Coinbase client libraries (official + advanced).
- Provides stable methods:
    - fetch_accounts()
    - fetch_open_orders()
    - fetch_fills(product_id=None)
    - place_market_order(product_id, side, size)
- Never raises uncaught exceptions during init or method calls (returns safe defaults).
- Logs detailed diagnostics to help troubleshooting.
"""
import os
import logging
import inspect
import traceback
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger("nija_client")
if not logger.handlers:
    # Basic fallback logging if app hasn't configured logging yet
    logging.basicConfig(level=logging.INFO)

# Names of wrapper methods — used to avoid accidentally calling wrapper methods
_WRAPPER_METHODS = {
    "fetch_accounts",
    "fetch_open_orders",
    "fetch_fills",
    "place_market_order",
    "_safe_client_call",
    "is_connected",
    "_has_method",
}


class CoinbaseClient:
    def __init__(self):
        """Initialize a robust Coinbase client wrapper."""
        logger.info("nija_client startup: loading Coinbase auth config")

        # Load env vars (expect these to exist in your container environment)
        self.api_key = os.getenv("COINBASE_API_KEY")
        self.api_secret = os.getenv("COINBASE_API_SECRET")
        self.org_id = os.getenv("COINBASE_ORG_ID")
        self.pem_content = os.getenv("COINBASE_PEM_CONTENT")
        self.base_url = os.getenv("COINBASE_BASE_URL", "https://api.coinbase.com")
        self.advanced = True  # user is using Coinbase Advanced

        # Diagnostics flags
        jwt_set = bool(self.pem_content)
        api_key_set = bool(self.api_key)
        org_id_set = bool(self.org_id)

        logger.info(f" - base={self.base_url}")
        logger.info(f" - advanced={self.advanced}")
        logger.info(f" - jwt_set={'yes' if jwt_set else 'no'}")
        logger.info(f" - api_key_set={'yes' if api_key_set else 'no'}")
        logger.info(f" - api_passphrase_set=no")
        logger.info(f" - org_id_set={'yes' if org_id_set else 'no'}")
        logger.info(f" - private_key_path_set=no")

        # Attempt to use installed official client libraries (non-fatal if absent)
        self.client = None
        self._client_type = None

        # Priority 1: coinbase_advanced (common package names vary)
        try:
            # try a few common import paths for Coinbase Advanced libs
            from coinbase_advanced.client import Client as AdvancedClient  # type: ignore
            try:
                if jwt_set:
                    self.client = AdvancedClient(
                        api_key=self.api_key,
                        api_secret=self.api_secret,
                        pem=self.pem_content,
                        org_id=self.org_id,
                        base_url=self.base_url,
                    )
                else:
                    self.client = AdvancedClient(
                        api_key=self.api_key, api_secret=self.api_secret, base_url=self.base_url
                    )
                self._client_type = "coinbase_advanced.Client"
                logger.info("Using coinbase_advanced.client.Client")
            except Exception as e:
                logger.info(f"coinbase_advanced.Client exists but failed to init: {e}")
                self.client = None
        except Exception:
            # not installed; move on
            pass

        # Priority 2: coinbase.rest (older official client)
        if self.client is None:
            try:
                from coinbase.rest import RESTClient  # type: ignore
                try:
                    # RESTClient variations differ, attempt safe init
                    self.client = RESTClient(key=self.api_key, secret=self.api_secret, base_url=self.base_url)
                    self._client_type = "coinbase.rest.RESTClient"
                    logger.info("Using coinbase.rest.RESTClient")
                except Exception as e:
                    logger.info(f"coinbase.rest.RESTClient import succeeded but init failed: {e}")
                    self.client = None
            except Exception:
                pass

        # Diagnostics: log underlying client class and attributes if present
        try:
            if self.client is not None:
                logger.info(f"Underlying client type: {type(self.client)}")
                # show only short attribute list to avoid huge logs
                try:
                    attrs = sorted([a for a in dir(self.client) if not a.startswith("_")])[:200]
                    logger.info(f"Underlying client attrs (sample): {attrs}")
                except Exception:
                    logger.debug("Could not list client attributes", exc_info=True)
            else:
                logger.info(
                    "No supported Coinbase client library detected or initialization failed. "
                    "Operations will safely no-op and log errors. To enable full functionality, "
                    "install 'coinbase_advanced' or 'coinbase' client package and ensure env vars are set."
                )
        except Exception:
            logger.debug("Diagnostics logging failed", exc_info=True)

        # Attempt a lightweight verification, but never let exceptions escape init
        try:
            if not self.is_connected():
                logger.error("🔹 Coinbase connection failed: unable to fetch accounts (client missing or returned no accounts)")
            else:
                logger.info("🔹 Coinbase connection appears OK (fetched accounts).")
        except Exception:
            # we protect init; log the stack for debugging but continue
            logger.error("🔹 Coinbase verification threw an exception:\n" + traceback.format_exc())

    # -----------------------------
    # Helper: check for a method on underlying client (not wrapper)
    # -----------------------------
    def _has_method(self, name: str) -> bool:
        """Return True if the underlying client has a callable attribute name."""
        try:
            return self.client is not None and hasattr(self.client, name) and callable(getattr(self.client, name))
        except Exception:
            return False

    # -----------------------------
    # Helper: call safely on underlying client or wrapper (avoid recursion)
    # -----------------------------
    def _safe_client_call(self, *names: str, default=None, **kwargs):
        """
        Try a list of attribute/method names on the underlying client (preferred) and then
        on this wrapper (only if the wrapper method is explicitly different to avoid recursion).
        Returns default on all failures.
        """
        for name in names:
            # Prefer underlying client methods — do not call wrapper methods with the same name
            try:
                if self.client is not None and hasattr(self.client, name):
                    attr = getattr(self.client, name)
                    if callable(attr):
                        try:
                            sig = inspect.signature(attr)
                            # Try to call with kwargs if it accepts them, else without
                            if kwargs and any(p.kind in (p.VAR_KEYWORD, p.KEYWORD_ONLY) for p in sig.parameters.values()):
                                return attr(**kwargs)
                            # if positional only or no params, attempt simple calls
                            if kwargs:
                                try:
                                    return attr(**kwargs)
                                except TypeError:
                                    return attr()
                            return attr()
                        except Exception:
                            # final attempt: try calling without kwargs
                            try:
                                return attr()
                            except Exception as e:
                                logger.debug(f"Call to client.{name} failed: {e}")
                                continue
                # Only consider wrapper methods if the requested name is NOT the wrapper's own public API
                if hasattr(self, name) and name not in _WRAPPER_METHODS:
                    attr = getattr(self, name)
                    if callable(attr):
                        try:
                            return attr(**kwargs) if kwargs else attr()
                        except TypeError:
                            try:
                                return attr()
                            except Exception as e:
                                logger.debug(f"Call to wrapper.{name} failed: {e}")
                                continue
            except Exception as e:
                logger.debug(f"Attempt to call {name} on client/wrapper failed: {e}")
                continue
        return default

    # -----------------------------
    # Connectivity helper
    # -----------------------------
    def is_connected(self) -> bool:
        """
        Return True if we can fetch (non-empty) accounts from the underlying client.
        This method is defensive and never raises.
        """
        try:
            # Try underlying client method names first
            result = None
            if self.client is not None:
                # try common client method signatures that return accounts
                for name in ("fetch_accounts", "get_accounts", "list_accounts", "accounts", "get_account_list"):
                    if self._has_method(name):
                        try:
                            method = getattr(self.client, name)
                            try:
                                accounts = method()
                            except TypeError:
                                accounts = method(params={})
                            result = accounts
                            break
                        except Exception:
                            logger.debug(f"is_connected: client method {name} call failed", exc_info=True)
                            continue
            # fallback to wrapper's own fetch_accounts (safe)
            if result is None:
                result = self.fetch_accounts()
            if not result:
                return False
            # if result is list-like and has items, connected
            try:
                if isinstance(result, list) and len(result) > 0:
                    return True
                if isinstance(result, dict) and result.get("accounts"):
                    return bool(result.get("accounts"))
            except Exception:
                return False
            return False
        except Exception:
            logger.debug("is_connected check failed", exc_info=True)
            return False

    # -----------------------------
    # Public API methods (defensive)
    # -----------------------------
    def fetch_accounts(self) -> List[Dict[str, Any]]:
        """
        Return list of accounts. Try several common client method names.
        Always returns a list (empty on error).
        """
        try:
            # Prefer underlying client methods via _safe_client_call
            result = self._safe_client_call(
                "fetch_accounts", "get_accounts", "list_accounts", "accounts", "get_account_list", default=None
            )
            if result is None:
                logger.error("fetch_accounts: no client method succeeded; returning empty list.")
                return []
            # normalize common shapes
            if isinstance(result, dict) and "accounts" in result:
                return result["accounts"] or []
            if isinstance(result, list):
                return result
            # try to coerce iterable
            try:
                return list(result)
            except Exception:
                logger.error("fetch_accounts: unexpected result shape; returning empty list.")
                return []
        except Exception as e:
            logger.error(f"fetch_accounts exception: {e}")
            return []

    def fetch_open_orders(self) -> List[Dict[str, Any]]:
        """
        Return list of open orders. Always returns list (empty on error).
        """
        try:
            result = self._safe_client_call(
                "fetch_open_orders", "get_orders", "list_orders", "open_orders", "orders", default=None
            )
            if result is None:
                logger.info("fetch_open_orders: no client method available; returning empty list.")
                return []
            if isinstance(result, dict) and "orders" in result:
                return result["orders"] or []
            if isinstance(result, list):
                return result
            try:
                return list(result)
            except Exception:
                logger.error("fetch_open_orders: unexpected result shape; returning empty list.")
                return []
        except Exception as e:
            logger.error(f"fetch_open_orders exception: {e}")
            return []

    def fetch_fills(self, product_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Return list of fills (executed trades). Accepts optional product_id.
        Always returns list (empty on error).
        """
        try:
            if product_id:
                result = self._safe_client_call("fetch_fills", "get_fills", "list_fills", default=None, product_id=product_id)
            else:
                result = self._safe_client_call("fetch_fills", "get_fills", "list_fills", "fills", default=None)
            if result is None:
                logger.info("fetch_fills: no client method available; returning empty list.")
                return []
            if isinstance(result, dict) and "fills" in result:
                return result["fills"] or []
            if isinstance(result, list):
                return result
            try:
                return list(result)
            except Exception:
                logger.error("fetch_fills: unexpected result shape; returning empty list.")
                return []
        except Exception as e:
            logger.error(f"fetch_fills exception: {e}")
            return []

    def place_market_order(self, product_id: str, side: str, size: float) -> Optional[Dict[str, Any]]:
        """
        Place a market order. Returns order dict on success or None on failure.
        This attempts several common client methods. Does not raise.
        """
        try:
            payload = {
                "product_id": product_id,
                "side": side,
                # clients differ - many expect strings for size
                "size": str(size),
                # some advanced clients expect nested config; we try simple first
                "type": "market",
            }
            # 1) try client.create_order if present
            if self.client is not None and hasattr(self.client, "create_order"):
                try:
                    return getattr(self.client, "create_order")(payload)
                except TypeError:
                    try:
                        return getattr(self.client, "create_order")(product_id=product_id, side=side, size=str(size), order_type="market")
                    except Exception:
                        logger.debug("client.create_order variants failed", exc_info=True)

            # 2) place_order / post_order / create variants
            result = self._safe_client_call("place_order", "post_order", "create", default=None, order=payload)
            if result is not None:
                return result

            logger.error("place_market_order: no supported order method available on client.")
            return None
        except Exception as e:
            logger.error(f"place_market_order exception: {e}")
            return None

# End of nija_client.py
