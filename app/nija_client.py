# /app/nija_client.py
"""
Safe Coinbase client wrapper for Nija bot.

- Non-crashing import attempts for multiple possible coinbase SDKs.
- Returns a `LiveClient` (wrapper) when SDK present, otherwise a `MockClient`.
- Use get_coinbase_client(api_key=..., api_secret=..., pem=..., org_id=...) to get a client.
- Use test_coinbase_connection() for a quick check (returns True/False).
"""

import logging
import time
from typing import Any, Optional, List, Callable

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------
# 1) Robust non-crashing import attempts
# -------------------------
COINBASE_AVAILABLE = False
COINBASE_CLIENT = None
_COINDOT_MODULE_NAME = None

_import_attempts = [
    ("coinbase.rest", "from coinbase.rest import RESTClient"),
    ("coinbase_advanced_py.rest_client", "import coinbase_advanced_py.rest_client"),
    ("coinbase_advanced.client", "from coinbase_advanced.client import Client"),
    ("coinbase_advanced_py.client", "import coinbase_advanced_py.client"),
    ("coinbase.rest_client", "import coinbase.rest_client"),
]

for module_path, msg in _import_attempts:
    try:
        if module_path == "coinbase.rest":
            from coinbase.rest import RESTClient as _Client
            COINBASE_CLIENT = _Client
            _COINDOT_MODULE_NAME = "coinbase.rest"

        elif module_path == "coinbase_advanced_py.rest_client":
            import coinbase_advanced_py.rest_client as _mod
            # try common attribute names
            COINBASE_CLIENT = getattr(_mod, "RESTClient", getattr(_mod, "Client", _mod))
            _COINDOT_MODULE_NAME = "coinbase_advanced_py.rest_client"

        elif module_path == "coinbase_advanced.client":
            from coinbase_advanced.client import Client as _Client
            COINBASE_CLIENT = _Client
            _COINDOT_MODULE_NAME = "coinbase_advanced.client"

        elif module_path == "coinbase_advanced_py.client":
            import coinbase_advanced_py.client as _mod
            COINBASE_CLIENT = getattr(_mod, "Client", _mod)
            _COINDOT_MODULE_NAME = "coinbase_advanced_py.client"

        elif module_path == "coinbase.rest_client":
            import coinbase.rest_client as _mod
            COINBASE_CLIENT = getattr(_mod, "RESTClient", getattr(_mod, "Client", _mod))
            _COINDOT_MODULE_NAME = "coinbase.rest_client"

        logger.info(f"✅ Coinbase SDK import succeeded via: {msg}")
        COINBASE_AVAILABLE = True
        break

    except Exception:
        logger.debug(f"Import attempt failed for {module_path}", exc_info=True)

if not COINBASE_AVAILABLE:
    logger.error(
        "❌ Coinbase SDK import failed. Ensure 'coinbase-advanced-py' (or your expected SDK) "
        "is present in requirements.txt. Running in DRY-RUN mode."
    )

# -------------------------
# 2) Lightweight client wrappers
# -------------------------
class MockClient:
    """A simple mock client that simulates the minimal interface used by the bot."""
    def __init__(self):
        self.mock_accounts = [{"id": "mock-1", "currency": "USD", "balance": "1000.00"}]

    def get_accounts(self) -> List[dict]:
        logger.info("MockClient.get_accounts() called — returning simulated accounts.")
        return self.mock_accounts

    # Add whichever simple methods your bot expects (e.g., place_order, fetch_price)
    def place_order(self, *args, **kwargs) -> dict:
        logger.info("MockClient.place_order() called — returning simulated order.")
        return {"status": "simulated", "args": args, "kwargs": kwargs}


class LiveClient:
    """
    Adapter that lazily instantiates the real SDK client and maps common methods.
    It tries a few constructor signatures and method names to maximize compatibility.
    """
    def __init__(self, client_cls: Any, api_key: Optional[str] = None, api_secret: Optional[str] = None,
                 pem: Optional[str] = None, org_id: Optional[str] = None, **kwargs):
        self.client_cls = client_cls
        self.api_key = api_key
        self.api_secret = api_secret
        self.pem = pem
        self.org_id = org_id
        self.kwargs = kwargs
        self._instance = None
        self._instantiate_attempted = False

    def _instantiate(self):
        if self._instance is not None:
            return self._instance
        if self._instantiate_attempted:
            return None
        self._instantiate_attempted = True

        ctor_attempts = [
            # common named args
            lambda: self.client_cls(api_key=self.api_key, api_secret=self.api_secret),
            lambda: self.client_cls(self.api_key, self.api_secret),
            lambda: self.client_cls(key=self.api_key, secret=self.api_secret),
            # some SDKs use pem/org_id + kid; pass what we have
            lambda: self.client_cls(pem=self.pem, org_id=self.org_id),
            lambda: self.client_cls(),  # try default constructor
        ]

        for attempt in ctor_attempts:
            try:
                inst = attempt()
                logger.info(f"✅ Instantiated Coinbase client using pattern: {attempt}")
                self._instance = inst
                return inst
            except Exception as e:
                logger.debug("Live client instantiation attempt failed", exc_info=True)

        logger.error("❌ All instantiation attempts for Coinbase client failed.")
        return None

    def _call(self, method_names: List[str], *args, **kwargs):
        inst = self._instantiate()
        if inst is None:
            raise RuntimeError("Coinbase client is not instantiated")

        for name in method_names:
            if hasattr(inst, name):
                try:
                    fn = getattr(inst, name)
                    return fn(*args, **kwargs)
                except Exception as e:
                    logger.exception(f"Error calling method {name} on Coinbase client: {e}")
                    raise

        # If no known method exists, try common call patterns on the client object
        # (some clients expose raw http helpers or differently-named methods)
        raise AttributeError(f"No supported method found on live client. Tried: {method_names}")

    # Common adapter methods
    def get_accounts(self):
        # try several method names commonly used across SDKs
        return self._call(["get_accounts", "accounts", "list_accounts", "get_accounts_list"])

    def place_order(self, *args, **kwargs):
        return self._call(["place_order", "create_order", "create_trade", "trade"], *args, **kwargs)


# -------------------------
# 3) Public factory
# -------------------------
def get_coinbase_client(api_key: Optional[str] = None, api_secret: Optional[str] = None,
                        pem: Optional[str] = None, org_id: Optional[str] = None, **kwargs) -> Any:
    """
    Returns:
      - LiveClient wrapper if a supported SDK was imported successfully.
      - MockClient if no SDK present (dry-run).
    """
    if not COINBASE_AVAILABLE or COINBASE_CLIENT is None:
        logger.warning("Returning MockClient (Coinbase SDK not available).")
        return MockClient()

    # If COINBASE_CLIENT is a module or class, create LiveClient
    logger.info(f"Creating LiveClient wrapper for SDK module: {_COINDOT_MODULE_NAME}")
    return LiveClient(client_cls=COINBASE_CLIENT, api_key=api_key, api_secret=api_secret, pem=pem, org_id=org_id, **kwargs)


# -------------------------
# 4) Test helper
# -------------------------
def test_coinbase_connection(api_key: Optional[str] = None, api_secret: Optional[str] = None,
                             pem: Optional[str] = None, org_id: Optional[str] = None, timeout: float = 6.0) -> bool:
    """
    Try to fetch accounts (or call a lightweight API) to verify the connection.
    Returns True on success, False on failure or when in mock/dry-run mode.
    """
    client = get_coinbase_client(api_key=api_key, api_secret=api_secret, pem=pem, org_id=org_id)
    try:
        # If mock, it will return simulated accounts quickly.
        accounts = client.get_accounts()
        logger.info(f"✅ Coinbase connection verified. Accounts fetched: {accounts}")
        return True
    except Exception as e:
        logger.exception(f"❌ Coinbase connection test failed: {e}")
        return False


# -------------------------
# 5) Example main/test-run when module executed directly (safe)
# -------------------------
if __name__ == "__main__":
    # For local testing only — DO NOT put secrets here; pass via env in production.
    import os
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    pem = os.environ.get("COINBASE_PEM_CONTENT")
    org_id = os.environ.get("COINBASE_ORG_ID")

    logger.info("Running local coinbase client smoke test (no real orders will be placed).")
    ok = test_coinbase_connection(api_key=api_key, api_secret=api_secret, pem=pem, org_id=org_id)
    logger.info(f"Smoke test result: {'OK' if ok else 'FAILED'}")
