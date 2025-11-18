# --- SAFE, NON-CRASHING COINBASE IMPORT HANDLER ---
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

COINBASE_AVAILABLE = False
COINBASE_CLIENT = None

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
            COINBASE_CLIENT = getattr(_mod, "RESTClient", _mod)

        elif module_path == "coinbase_advanced.client":
            from coinbase_advanced.client import Client as _Client
            COINBASE_CLIENT = _Client

        elif module_path == "coinbase_advanced_py.client":
            import coinbase_advanced_py.client as _mod
            COINBASE_CLIENT = getattr(_mod, "Client", _mod)

        elif module_path == "coinbase.rest_client":
            import coinbase.rest_client as _mod
            COINBASE_CLIENT = getattr(_mod, "RESTClient", _mod)

        logger.info(f"✅ Coinbase SDK import succeeded via: {msg}")
        COINBASE_AVAILABLE = True
        break

    except Exception:
        logger.debug(f"Import attempt failed for {module_path}", exc_info=True)

if not COINBASE_AVAILABLE:
    logger.error(
        "❌ Coinbase SDK import failed. Ensure 'coinbase-advanced-py' is in "
        "requirements.txt. Running in DRY-RUN MODE — guard all Coinbase calls "
        "with COINBASE_AVAILABLE."
    )

# --- EXAMPLE USAGE / FALLBACK ---
def get_coinbase_client(api_key=None, api_secret=None):
    """
    Unified method to safely create a Coinbase client
    or fallback to dry-run.
    """
    if not COINBASE_AVAILABLE:
        logger.warning("⚠️ Coinbase unavailable — skipping live trade and using dry-run mode.")
        return None  # or return a mock object if you want

    # LIVE client
    try:
        return COINBASE_CLIENT(api_key=api_key, api_secret=api_secret)
    except Exception as e:
        logger.error(f"❌ Failed to initialize Coinbase client: {e}")
        return None

# /app/nija_client.py
import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Try multiple import names (some environments use different package names)
_CLIENT_MODULE = None
for try_name in ("coinbase_advanced_py", "coinbase_advanced"):
    try:
        _m = __import__(try_name)
        _CLIENT_MODULE = try_name
        break
    except Exception:
        _m = None

# Try to import known client entrypoints for each package name
Client = None
if _CLIENT_MODULE == "coinbase_advanced_py":
    try:
        from coinbase_advanced_py import Client  # preferred import
    except Exception:
        Client = None
elif _CLIENT_MODULE == "coinbase_advanced":
    try:
        # some forks expose client under different path
        from coinbase_advanced.client import Client
    except Exception:
        Client = None

class CoinbaseClient:
    """
    Minimal wrapper around the Coinbase Advanced client.
    Expects either:
      - coinbase_advanced_py installed and importable as `coinbase_advanced_py`
    or
      - coinbase_advanced installed and importable as `coinbase_advanced.client.Client`

    Initialization reads credentials from provided args (preferred) or from environment variables:
      - api_key or COINBASE_API_KEY
      - api_secret_path or COINBASE_API_SECRET_PATH (PEM file)
      - jwt_pem (PEM text) or COINBASE_JWT_PEM (text)
      - jwt_kid or COINBASE_JWT_KID
      - issuer or COINBASE_JWT_ISSUER
      - org_id or COINBASE_ORG_ID
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret_path: Optional[str] = None,
        jwt_pem: Optional[str] = None,
        jwt_kid: Optional[str] = None,
        issuer: Optional[str] = None,
        org_id: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        # env fallbacks
        self.api_key = api_key or os.getenv("COINBASE_API_KEY")
        self.api_secret_path = api_secret_path or os.getenv("COINBASE_API_SECRET_PATH") or os.getenv("COINBASE_PEM_PATH")
        self.jwt_pem = jwt_pem or os.getenv("COINBASE_JWT_PEM") or os.getenv("COINBASE_PEM_CONTENT")
        self.jwt_kid = jwt_kid or os.getenv("COINBASE_JWT_KID")
        self.issuer = issuer or os.getenv("COINBASE_JWT_ISSUER")
        self.org_id = org_id or os.getenv("COINBASE_ORG_ID")
        self.base_url = base_url or os.getenv("COINBASE_API_BASE") or os.getenv("COINBASE_ADVANCED_BASE")

        self._client = None
        self._available = False

        # quick validations
        if not (self.api_key or (self.jwt_pem and self.jwt_kid and self.issuer and self.org_id)):
            raise RuntimeError("Missing Coinbase credentials or org ID! Provide COINBASE_API_KEY or full JWT creds.")

        # Try to initialize the installed client library (if available)
        if Client is None:
            logger.warning("Coinbase SDK not installed or importable. Coinbase client methods will be unavailable.")
            self._available = False
            return

        try:
            # Many official libs accept different init args — try common constructors.
            # 1) coinbase_advanced_py.Client(api_key=..., api_secret_path=..., base_url=...)
            # 2) coinbase_advanced.client.Client(...)

            kwargs = {}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.api_secret_path:
                kwargs["api_secret_path"] = self.api_secret_path
            if self.base_url:
                kwargs["base_url"] = self.base_url

            # if the client expects jwt/issuer/etc, pass them
            if hasattr(Client, "__init__"):
                # don't assume exact signature — attempt to init with common kwargs
                self._client = Client(**kwargs)
            else:
                # fallback: try simple instantiation
                self._client = Client(self.api_key)
            self._available = True
            logger.info("✅ Coinbase client initialized (wrapper).")
        except Exception as e:
            logger.exception("Failed to initialize Coinbase client library: %s", e)
            self._available = False

    @property
    def available(self) -> bool:
        return self._available and self._client is not None

    # --- wrapper methods you will call from trading code ---
    def get_accounts(self):
        """
        Returns list of accounts (in library's format) or raises.
        """
        if not self.available:
            raise RuntimeError("Coinbase client not available")
        # library differences: try known method names
        if hasattr(self._client, "get_accounts"):
            return self._client.get_accounts()
        if hasattr(self._client, "accounts"):
            return self._client.accounts()
        # fallback: try generic request method if available
        if hasattr(self._client, "request"):
            return self._client.request("GET", "/brokerage/accounts")
        raise RuntimeError("get_accounts not supported by installed client wrapper")

    def create_order(self, product_id: str, side: str, type: str = "market", size: str = None, price: str = None, **kwargs):
        """
        Create a market/limit order. Size and price must be strings for many Coinbase clients.
        Returns order object / dict.
        """
        if not self.available:
            raise RuntimeError("Coinbase client not available")

        # standard call shape for coinbase_advanced_py
        try:
            # try common signatures
            if hasattr(self._client, "create_order"):
                return self._client.create_order(product_id=product_id, side=side, type=type, size=size, price=price, **kwargs)
            if hasattr(self._client, "orders") and callable(self._client.orders):
                # some clients use orders.create
                orders = self._client.orders
                if hasattr(orders, "create"):
                    return orders.create(product_id=product_id, side=side, type=type, size=size, price=price, **kwargs)
            # last resort: generic request method
            if hasattr(self._client, "request"):
                payload = {"product_id": product_id, "side": side, "type": type}
                if size: payload["size"] = str(size)
                if price: payload["price"] = str(price)
                return self._client.request("POST", "/brokerage/orders", json=payload)
        except Exception as e:
            logger.exception("create_order error: %s", e)
            raise

        raise RuntimeError("create_order not supported by installed client wrapper")
