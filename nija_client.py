# /nija_client.py
"""
Safe Coinbase client wrapper for Nija bot.
- Uses LiveClient if SDK is installed, otherwise MockClient (dry-run)
"""

import logging
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

COINBASE_AVAILABLE = False
COINBASE_CLIENT = None

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
        elif module_path == "coinbase_advanced_py.rest_client":
            import coinbase_advanced_py.rest_client as _mod
            COINBASE_CLIENT = getattr(_mod, "RESTClient", getattr(_mod, "Client", _mod))
        elif module_path == "coinbase_advanced.client":
            from coinbase_advanced.client import Client as _Client
            COINBASE_CLIENT = _Client
        elif module_path == "coinbase_advanced_py.client":
            import coinbase_advanced_py.client as _mod
            COINBASE_CLIENT = getattr(_mod, "Client", _mod)
        elif module_path == "coinbase.rest_client":
            import coinbase.rest_client as _mod
            COINBASE_CLIENT = getattr(_mod, "RESTClient", getattr(_mod, "Client", _mod))

        logger.info(f"✅ Coinbase SDK import succeeded via: {msg}")
        COINBASE_AVAILABLE = True
        break

    except Exception:
        logger.debug(f"Import attempt failed for {module_path}", exc_info=True)

if not COINBASE_AVAILABLE:
    logger.warning("❌ Coinbase SDK import failed. Running in DRY-RUN mode.")


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

    def _instantiate(self):
        if self._instance:
            return self._instance
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
