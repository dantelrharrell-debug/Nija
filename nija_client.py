import sys
import os
import importlib
import logging
import traceback

# ---------------- Logger Setup ----------------
logger = logging.getLogger("nija.nija_client")
logger.setLevel(logging.INFO)
if not logger.handlers:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(h)

# ---------------- Constants ----------------
MODULE_NAME = "coinbase_advanced_py"

# ---------------- Remove Shadowing Folders ----------------
def remove_shadowing_folder(module_name=MODULE_NAME):
    cwd = os.path.abspath(os.getcwd())
    removed = []
    for p in list(sys.path):
        if not p:
            continue
        abs_p = os.path.abspath(p)
        if abs_p.startswith(cwd):
            if ".venv" in abs_p or "venv" in abs_p:
                continue
            folder_candidate = os.path.join(abs_p, module_name)
            if os.path.exists(folder_candidate):
                new_name = folder_candidate + "_disabled"
                os.rename(folder_candidate, new_name)
                removed.append(folder_candidate)
    if removed:
        logger.info(f"[NIJA-SHIM] Disabled local shadowing folders: {removed}")

remove_shadowing_folder()

# ---------------- Prioritize site-packages ----------------
def prioritize_site_packages(module_name=MODULE_NAME):
    venv_path = os.path.join(sys.prefix, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages")
    if os.path.exists(venv_path) and venv_path not in sys.path:
        sys.path.insert(0, venv_path)
        logger.info(f"[NIJA-SHIM] Added venv site-packages to sys.path: {venv_path}")
    try:
        m = importlib.import_module(module_name)
        logger.info(f"[NIJA-SHIM] Successfully imported {module_name} from: {getattr(m, '__file__', getattr(m, '__path__', None))}")
        return m
    except Exception as e:
        logger.exception(f"[NIJA-SHIM] Failed to import {module_name}: {e}")
        return None

coinbase_module = prioritize_site_packages()

# ---------------- Load CoinbaseClient or Dummy ----------------
if coinbase_module:
    try:
        CoinbaseClient = getattr(coinbase_module, "CoinbaseClient")
        logger.info("[NIJA-SHIM] Found CoinbaseClient in coinbase_advanced_py")
    except AttributeError:
        CoinbaseClient = None
        logger.warning("[NIJA-SHIM] CoinbaseClient attribute not found in module.")
else:
    CoinbaseClient = None

if CoinbaseClient is None:
    # fallback to DummyClient
    class DummyClient:
        def __init__(self):
            logger.warning("Using DummyClient: real Coinbase client not available.")

        def get_accounts(self):
            return []

        def place_order(self, *args, **kwargs):
            logger.warning("DummyClient.place_order called — no-op. args=%s kwargs=%s", args, kwargs)
            return None

    CoinbaseClient = DummyClient
    logger.warning("Using DummyClient: real Coinbase client not available.")

# ---------------- Load Environment ----------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_PASSPHRASE")
SANDBOX = os.getenv("SANDBOX", "True").lower() == "true"

def masked(v):
    if v is None: return None
    s = str(v)
    if len(s) <= 6: return "*****"
    return s[:3] + "..." + s[-3:]

logger.info(f"Environment (masked): COINBASE_API_KEY={masked(API_KEY)} COINBASE_API_SECRET={masked(API_SECRET)} COINBASE_PASSPHRASE={masked(API_PASSPHRASE)} SANDBOX={SANDBOX}")

# ---------------- Instantiate Client ----------------
_client_ready = False
client = None
try:
    client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, passphrase=API_PASSPHRASE, sandbox=SANDBOX)
    _client_ready = not isinstance(client, DummyClient)
    if _client_ready:
        logger.info("CoinbaseClient instantiated successfully (sandbox=%s). Live trading possible.", SANDBOX)
except TypeError:
    # For DummyClient or old-style client classes
    client = CoinbaseClient()
    _client_ready = False
    logger.warning("CoinbaseClient instantiation failed. Using DummyClient fallback.")

REAL_CLIENT_ACTIVE = _client_ready

# ---------------- Public Helpers ----------------
def get_accounts():
    try:
        accounts = client.get_accounts()
        return accounts if accounts else []
    except Exception as e:
        logger.exception("Error in get_accounts(): %s", e)
        return []

def place_order(symbol, side, size, order_type="market"):
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

# ---------------- Startup Log Summary ----------------
if REAL_CLIENT_ACTIVE:
    logger.info("nija_client: Real Coinbase client ready. Live trading active.")
else:
    logger.warning("nija_client: Running with DummyClient — no live trading. Fix coinbase_advanced_py import to enable live trading.")
