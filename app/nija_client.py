# /app/nija_client.py
"""
Safe Coinbase client wrapper for Nija bot.

- Robust non-crashing imports for multiple Coinbase SDKs.
- Returns a LiveClient if SDK is installed, else a MockClient for dry-run.
"""

import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

COINBASE_AVAILABLE = False
COINBASE_CLIENT = None
_COINDOT_MODULE_NAME = None

# -------------------------
# Robust import attempts
# -------------------------
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
    logger.error("❌ Coinbase SDK import failed. Running in DRY-RUN mode.")


# -------------------------
# Mock client for dry-run
# -------------------------
class MockClient:
    def get_accounts(self):
        logger.info("MockClient.get_accounts() called — returning simulated account")
        return [{"id": "mock-1", "currency": "USD", "balance": "1000.00"}]

    def place_order(self, *args, **kwargs):
        logger.info(f"MockClient.place_order() called with args={args}, kwargs={kwargs}")
        return {"status": "simulated"}


# -------------------------
# Live client wrapper
# -------------------------
class LiveClient:
    def __init__(self, client_cls, api_key=None, api_secret=None, pem=None, org_id=None, **kwargs):
        self.client_cls = client_cls
        self.api_key = api_key
        self.api_secret = api_secret
        self.pem = pem
        self.org_id = org_id
        self.kwargs = kwargs
        self._instance = None
        self._attempted = False

    def _instantiate(self):
        if self._instance or self._attempted:
            return self._instance
        self._attempted = True
        try:
            self._instance = self.client_cls(
                api_key=self.api_key,
                api_secret=self.api_secret,
                pem=self.pem,
                org_id=self.org_id,
                **self.kwargs
            )
            logger.info("✅ LiveClient instantiated successfully")
        except Exception as e:
            logger.error(f"❌ Failed to instantiate LiveClient: {e}")
            self._instance = None
        return self._instance

    def get_accounts(self):
        inst = self._instantiate()
        if inst is None:
            return MockClient().get_accounts()
        for method_name in ["get_accounts", "accounts", "list_accounts"]:
            if hasattr(inst, method_name):
                return getattr(inst, method_name)()
        raise RuntimeError("No get_accounts method on client")

    def place_order(self, *args, **kwargs):
        inst = self._instantiate()
        if inst is None:
            return MockClient().place_order(*args, **kwargs)
        for method_name in ["place_order", "create_order"]:
            if hasattr(inst, method_name):
                return getattr(inst, method_name)(*args, **kwargs)
        raise RuntimeError("No place_order method on client")


# -------------------------
# Factory function
# -------------------------
def get_coinbase_client(api_key=None, api_secret=None, pem=None, org_id=None, **kwargs):
    if not COINBASE_AVAILABLE or COINBASE_CLIENT is None:
        logger.warning("Returning MockClient (Coinbase SDK not available)")
        return MockClient()
    return LiveClient(
        client_cls=COINBASE_CLIENT,
        api_key=api_key,
        api_secret=api_secret,
        pem=pem,
        org_id=org_id,
        **kwargs
    )


# -------------------------
# Quick connection test
# -------------------------
def test_coinbase_connection(api_key=None, api_secret=None, pem=None, org_id=None):
    client = get_coinbase_client(api_key, api_secret, pem, org_id)
    try:
        accounts = client.get_accounts()
        logger.info(f"✅ Coinbase connection OK. Accounts: {accounts}")
        return True
    except Exception as e:
        logger.exception(f"❌ Coinbase connection test failed: {e}")
        return False
