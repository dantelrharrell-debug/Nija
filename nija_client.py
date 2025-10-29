# nija_client.py
import sys
import os
import importlib
import logging
from decimal import Decimal

# ----------------- Logger Setup -----------------
logger = logging.getLogger("nija.nija_client")
logger.setLevel(logging.INFO)
if not logger.handlers:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(h)

# ----------------- Environment -----------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_PASSPHRASE")
SANDBOX = os.getenv("SANDBOX", "True").lower() == "true"

def masked(v):
    if v is None:
        return None
    s = str(v)
    if len(s) <= 6:
        return "*****"
    return s[:3] + "..." + s[-3:]

logger.info(
    f"Environment (masked): COINBASE_API_KEY={masked(API_KEY)} "
    f"COINBASE_API_SECRET={masked(API_SECRET)} "
    f"COINBASE_PASSPHRASE={masked(API_PASSPHRASE)} "
    f"SANDBOX={SANDBOX}"
)

# ----------------- Shadowing Fix -----------------
def remove_shadowing_folder(module_name="coinbase_advanced_py"):
    """
    Remove local folders that could shadow the real site-packages module.
    No renaming; just remove from sys.path to avoid cross-device errors.
    """
    cwd = os.path.abspath(os.getcwd())
    removed = []
    for p in list(sys.path):
        if not p:
            continue
        abs_p = os.path.abspath(p)
        if abs_p.startswith(cwd):
            folder_candidate = os.path.join(abs_p, module_name)
            if os.path.exists(folder_candidate):
                if p in sys.path:
                    sys.path.remove(p)
                    removed.append(p)
    if removed:
        logger.info(f"[NIJA-SHIM] Removed local sys.path entries that could shadow packages: {removed}")

remove_shadowing_folder()

# ----------------- Prioritize site-packages -----------------
venv_path = os.path.join(
    sys.prefix, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages"
)
if os.path.exists(venv_path) and venv_path not in sys.path:
    sys.path.insert(0, venv_path)
    logger.info(f"[NIJA-SHIM] Added venv site-packages to sys.path: {venv_path}")

# ----------------- Import Coinbase Module -----------------
coinbase_module = None
try:
    coinbase_module = importlib.import_module("coinbase_advanced_py")
    logger.info(f"[NIJA-SHIM] Imported coinbase_advanced_py -> {getattr(coinbase_module, '__file__', getattr(coinbase_module, '__path__', None))}")
except Exception as e:
    logger.warning(f"[NIJA-SHIM] Failed to import coinbase_advanced_py: {e}")

# ----------------- Locate CoinbaseClient -----------------
CoinbaseClientClass = None
if coinbase_module:
    try:
        CoinbaseClientClass = getattr(coinbase_module, "CoinbaseClient")
    except AttributeError:
        CoinbaseClientClass = None

# ----------------- DummyClient Fallback -----------------
if CoinbaseClientClass is None:
    class DummyClient:
        def __init__(self):
            logger.warning("Using DummyClient: no live Coinbase integration available.")

        def get_accounts(self):
            return []

        def place_order(self, *args, **kwargs):
            logger.warning("DummyClient.place_order called — no-op. args=%s kwargs=%s", args, kwargs)
            return None

    CoinbaseClientClass = DummyClient
    logger.warning("Using DummyClient: real Coinbase client not available.")

# ----------------- Instantiate Client -----------------
client = None
_client_ready = False
try:
    client = CoinbaseClientClass(
        api_key=API_KEY,
        api_secret=API_SECRET,
        passphrase=API_PASSPHRASE,
        sandbox=SANDBOX
    )
    _client_ready = not isinstance(client, DummyClient)
    if _client_ready:
        logger.info(f"CoinbaseClient instantiated (sandbox={SANDBOX})")
except Exception as e:
    logger.exception(f"Failed to instantiate CoinbaseClient: {e}")
    client = DummyClient()
    _client_ready = False

REAL_CLIENT_ACTIVE = _client_ready

# ----------------- Helper Functions -----------------
def get_accounts():
    try:
        accounts = client.get_accounts()
        return accounts or []
    except Exception as e:
        logger.exception("Error in get_accounts(): %s", e)
        return []

def place_order(symbol, side, size, order_type="market"):
    try:
        try:
            return client.place_order(product_id=symbol, side=side, order_type=order_type, size=str(size))
        except TypeError:
            try:
                return client.place_order(product_id=symbol, side=side, size=str(size))
            except TypeError:
                return client.place_order(symbol, side, size, order_type)
    except Exception as e:
        logger.exception("Error placing order: %s", e)
        return None

# ----------------- Final Status -----------------
if REAL_CLIENT_ACTIVE:
    logger.info("nija_client: Real Coinbase client ready. Live trading possible (if SANDBOX=False).")
else:
    logger.warning("nija_client: Running with DummyClient — no live trading will occur until coinbase_advanced_py import is fixed.")
