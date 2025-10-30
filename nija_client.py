import os
import logging
from decimal import Decimal
import importlib

# --- Setup logging ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nija_client")

# ---------------------------
# Dummy fallback (safe)
# ---------------------------
class DummyClient:
    def __init__(self):
        logger.warning("[DummyClient] Simulation mode — live trading disabled")

    def get_accounts(self):
        logger.warning("[DummyClient] Returning simulated balances")
        return [{"currency": "USD", "balance": "10000.00"}]

    def get_spot_account_balances(self):
        return self.get_accounts()

    def place_order(self, *args, **kwargs):
        logger.info(f"[DummyClient] Simulated order: args={args} kwargs={kwargs}")
        return {"status": "simulated", "order": kwargs}

# ---------------------------
# Try multiple import paths
# ---------------------------
_client_candidates = []  # list of (name, class)
_import_attempts = []

def _try_imports():
    tries = [
        ("coinbase.rest.RESTClient", "from coinbase.rest import RESTClient"),
        ("coinbase.rest_client.RESTClient", "from coinbase.rest_client import RESTClient"),
        ("coinbase_advanced_py.RESTClient", "from coinbase_advanced_py import RESTClient"),
        ("coinbase_advanced_py.client.RESTClient", "from coinbase_advanced_py.client import RESTClient"),
        ("coinbase.advanced.RESTClient", "from coinbase.advanced import RESTClient"),
        ("coinbase.RESTClient", "from coinbase import RESTClient"),
    ]

    for name, hint in tries:
        parts = hint.replace("from ", "").split(" import ")
        module_name = parts[0].strip()
        attr_name = parts[1].strip()
        try:
            mod = importlib.import_module(module_name)
            client_cls = getattr(mod, attr_name)
            _client_candidates.append((f"{module_name}.{attr_name}", client_cls))
            _import_attempts.append((hint, "ok"))
            logger.info(f"[NIJA] Import succeeded: {hint}")
        except Exception as e:
            _import_attempts.append((hint, f"failed: {e}"))
            logger.debug(f"[NIJA-DEBUG] Import attempt {hint} failed: {e}")

_try_imports()

# ---------------------------
# Environment
# ---------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # may be None

# ---------------------------
# Instantiation attempts
# ---------------------------
def _instantiate_and_test(client_cls, *args, **kwargs):
    try:
        inst = client_cls(*args, **kwargs)
    except Exception as e:
        logger.debug(f"[NIJA-DEBUG] Instantiation failed for {client_cls} with args={args}, kwargs={kwargs}: {e}")
        return None
    try:
        # Test available account methods
        accounts = None
        if hasattr(inst, "get_spot_account_balances"):
            accounts = inst.get_spot_account_balances()
        elif hasattr(inst, "get_accounts"):
            accounts = inst.get_accounts()
        logger.debug(f"[NIJA-DEBUG] get_accounts returned: {accounts}")
        return inst
    except Exception as e:
        logger.debug(f"[NIJA-DEBUG] Test call failed for {client_cls}: {e}")
        return None

def init_client():
    logger.info(f"[NIJA] API_KEY present: {'yes' if API_KEY else 'no'}")
    logger.info(f"[NIJA] API_SECRET present: {'yes' if API_SECRET else 'no'}")
    logger.info(f"[NIJA] API_PASSPHRASE present: {'yes' if API_PASSPHRASE else 'no'}")

    if not (API_KEY and API_SECRET):
        logger.warning("[NIJA] Missing API key/secret — using DummyClient")
        return DummyClient()

    for name, cls in _client_candidates:
        logger.info(f"[NIJA] Trying candidate client: {name}")
        # Try positional args
        inst = _instantiate_and_test(cls, API_KEY, API_SECRET)
        if inst:
            logger.info(f"[NIJA] Authenticated using {name} with positional api_key/api_secret")
            return inst
        # Try keyword args
        inst = _instantiate_and_test(cls, api_key=API_KEY, api_secret=API_SECRET)
        if inst:
            logger.info(f"[NIJA] Authenticated using {name} with keyword api_key/api_secret")
            return inst
        # Try passphrase if present
        if API_PASSPHRASE:
            inst = _instantiate_and_test(cls, API_KEY, API_SECRET, API_PASSPHRASE)
            if inst:
                logger.info(f"[NIJA] Authenticated using {name} with positional passphrase")
                return inst
            inst = _instantiate_and_test(cls, api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE)
            if inst:
                logger.info(f"[NIJA] Authenticated using {name} with keyword passphrase")
                return inst

    logger.warning("[NIJA] No working Coinbase client found. Falling back to DummyClient.")
    # log all import attempts
    for attempt, result in _import_attempts:
        logger.debug(f"[NIJA-DEBUG] Import attempt: {attempt} -> {result}")
    return DummyClient()

# ---------------------------
# Global client
# ---------------------------
client = init_client()

# ---------------------------
# Helper to get USD balance
# ---------------------------
def get_usd_balance(client):
    try:
        if hasattr(client, "get_spot_account_balances"):
            balances = client.get_spot_account_balances()
        else:
            balances = client.get_accounts()
        for a in balances:
            if a.get("currency") == "USD":
                return Decimal(a.get("balance", "0"))
    except Exception as e:
        logger.warning(f"[NIJA-DEBUG] Could not fetch balances: {e}")
    return Decimal("0")

# Log initialized client
logger.info(f"[NIJA] Initialized client: {type(client).__name__}. USD balance: {get_usd_balance(client)}")
