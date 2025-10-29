import sys
import os
import importlib
import logging
import traceback

logger = logging.getLogger("nija.nija_client")
logger.setLevel(logging.INFO)
if not logger.handlers:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(h)

# --- BEGIN: Shadowing folder auto-disable shim ---
MODULE_NAME = "coinbase_advanced_py"

def remove_shadowing_folder(module_name=MODULE_NAME):
    cwd = os.path.abspath(os.getcwd())
    removed = []
    for p in list(sys.path):
        if not p:
            continue
        abs_p = os.path.abspath(p)
        if abs_p.startswith(cwd):
            # Skip virtualenv
            if ".venv" in abs_p or "venv" in abs_p:
                continue
            folder_candidate = os.path.join(abs_p, module_name)
            if os.path.exists(folder_candidate):
                # Rename folder instead of deleting
                new_name = folder_candidate + "_disabled"
                os.rename(folder_candidate, new_name)
                removed.append(folder_candidate)
    if removed:
        logger.info(f"[NIJA-SHIM] Disabled local shadowing folders: {removed}")

remove_shadowing_folder()
# --- END shim ---

# --- BEGIN: prioritize site-packages and import real module ---
def prioritize_site_packages(module_name=MODULE_NAME):
    """Ensure the real site-packages version loads, not a local folder."""
    # Add virtualenv site-packages to front
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
# --- END shim ---

# --- BEGIN: Load CoinbaseClient or fallback ---
if coinbase_module:
    try:
        CoinbaseClient = getattr(coinbase_module, "CoinbaseClient")
    except AttributeError:
        CoinbaseClient = None
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
# --- END CoinbaseClient shim ---

# ---------- Standard environment setup ----------
import os

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

# ---------- Instantiate client ----------
try:
    client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, passphrase=API_PASSPHRASE, sandbox=SANDBOX)
    REAL_CLIENT_ACTIVE = not isinstance(client, DummyClient)
    if REAL_CLIENT_ACTIVE:
        logger.info("CoinbaseClient instantiated (sandbox=%s).", SANDBOX)
except TypeError:
    # DummyClient fallback for old-style class
    client = CoinbaseClient()
    REAL_CLIENT_ACTIVE = False

# ---------- Public helpers ----------
def get_accounts():
    try:
        accounts = client.get_accounts()
        if accounts is None:
            return []
        return accounts
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

if REAL_CLIENT_ACTIVE:
    logger.info("nija_client: Real Coinbase client ready. Live trading possible.")
else:
    logger.warning("nija_client: Real Coinbase client NOT ready. Running with DummyClient — no live trading will occur until coinbase_advanced_py import is fixed.")
