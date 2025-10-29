# nija_client.py
# ---------- NIJA: site-packages import shim + robust fallback ----------
import sys, os, importlib, traceback, logging, time
logger = logging.getLogger("nija.nija_client")
logger.setLevel(logging.INFO)
if not logger.handlers:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(h)

def find_site_pkgs_with_module(module_name="coinbase_advanced_py"):
    for p in sys.path:
        if not p:
            continue
        low = str(p).lower()
        if ("site-packages" in low) or ("dist-packages" in low) or p.endswith(".egg"):
            modpath = os.path.join(p, module_name)
            if os.path.exists(modpath):
                return p, modpath
    # fallback: return first site-packages-like path
    for p in sys.path:
        if p and (("site-packages" in p) or ("dist-packages" in p)):
            return p, None
    return None, None

# Try to prioritize real site-packages if present (avoid repo shadowing)
site_pkgs_path, modpath = find_site_pkgs_with_module()
if site_pkgs_path:
    try:
        if site_pkgs_path not in sys.path:
            sys.path.insert(0, site_pkgs_path)
        elif sys.path[0] != site_pkgs_path:
            sys.path.remove(site_pkgs_path)
            sys.path.insert(0, site_pkgs_path)
        logger.info(f"[NIJA-SHIM] Prioritized site-packages: {site_pkgs_path}; module path exists: {bool(modpath)}")
    except Exception:
        logger.exception("[NIJA-SHIM] Error adjusting sys.path for site-packages")
else:
    # Remove suspicious local repo-shadowing entries that could shadow installed package
    cwd = os.path.abspath(os.getcwd())
    removed = []
    for p in list(sys.path):
        try:
            if p and os.path.abspath(p).startswith(cwd) and "site-packages" not in p:
                # keep virtualenv / .venv paths
                if ".venv" in p or "venv" in p or ".virtualenv" in p:
                    continue
                sys.path.remove(p)
                removed.append(p)
        except Exception:
            pass
    if removed:
        logger.info(f"[NIJA-SHIM] Removed local sys.path entries that could shadow packages: {removed}")

def locate_coinbase_client():
    tried = []
    candidates = [
        "coinbase_advanced_py",
        "coinbase_advanced_py.client",
        "coinbase_advanced_py.client.client",
    ]
    for name in candidates:
        try:
            m = importlib.import_module(name)
            tried.append((name, getattr(m, "__file__", getattr(m, "__path__", None))))
            logger.info(f"[NIJA-SHIM] Imported {name} -> {getattr(m, '__file__', getattr(m, '__path__', None))}")
            for attr in ("CoinbaseClient", "CoinbaseAdvancedClient", "CoinbaseClientV1"):
                if hasattr(m, attr):
                    logger.info(f"[NIJA-SHIM] Found client class '{attr}' in {name}")
                    return getattr(m, attr)
        except Exception as e:
            tried.append((name, repr(e)))
            logger.debug(f"[NIJA-SHIM] import {name} failed: {e}")

    # try top-level exposure again
    try:
        m_top = importlib.import_module("coinbase_advanced_py")
        if hasattr(m_top, "CoinbaseClient"):
            logger.info("[NIJA-SHIM] Found CoinbaseClient on top-level coinbase_advanced_py")
            return getattr(m_top, "CoinbaseClient")
    except Exception:
        pass

    logger.error("[NIJA-SHIM] No usable Coinbase client class found. Import attempts: %s", tried)
    return None

CoinbaseClientClass = locate_coinbase_client()

# ---- If you prefer strict failure: raise here instead of fallback ----
# If CoinbaseClientClass is None we will continue but use a DummyClient below
if CoinbaseClientClass is None:
    logger.error("[NIJA-SHIM] Coinbase client class not located in installed package. Falling back to DummyClient (no live trading).")
    logger.error("[NIJA-SHIM] Common root cause: a repository folder named './coinbase_advanced_py' is shadowing the installed package. DELETE or RENAME that folder to let the real package load from site-packages.")
else:
    logger.info("[NIJA-SHIM] Coinbase client class available: %s", CoinbaseClientClass)

# ---------- Standard imports and configuration ----------
from decimal import Decimal

# Load environment variables
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

# ---------- Real client instantiation (if available) ----------
client = None
_client_ready = False

if CoinbaseClientClass is not None:
    try:
        # attempt to construct the real client
        client = CoinbaseClientClass(
            api_key=API_KEY,
            api_secret=API_SECRET,
            passphrase=API_PASSPHRASE,
            sandbox=SANDBOX
        )
        _client_ready = True
        logger.info("CoinbaseClient instantiated (sandbox=%s).", SANDBOX)
    except Exception as e:
        logger.exception("Failed to instantiate CoinbaseClient: %s", e)
        client = None
        _client_ready = False

# ---------- Dummy client fallback so service stays up (no live trades) ----------
class DummyClient:
    """
    Minimal dummy client that matches the small subset of methods we use:
    - get_accounts() -> []
    - place_order(...) -> raises or returns None
    """
    def __init__(self):
        logger.warning("Using DummyClient: no live Coinbase integration available.")

    def get_accounts(self):
        # return empty list to indicate no accounts found
        return []

    def place_order(self, *args, **kwargs):
        logger.warning("DummyClient.place_order called — no-op. args=%s kwargs=%s", args, kwargs)
        return None

if not _client_ready or client is None:
    client = DummyClient()
    _client_ready = False

# ---------- Public helper functions used by nija_live_snapshot.py ----------
def get_accounts():
    """
    Returns a list of accounts (or empty list).
    """
    try:
        accounts = client.get_accounts()
        # Some client libs return a dict or object — normalize to list-like if possible
        if accounts is None:
            return []
        return accounts
    except Exception as e:
        logger.exception("Error in get_accounts(): %s", e)
        return []

def place_order(symbol, side, size, order_type="market"):
    """
    Place a trade order through the client.
    Returns the underlying client response, or None on failure / dummy.
    """
    try:
        # many coinbase libs use product_id / product or symbol naming differences.
        # If the real client expects 'product_id' we pass it; if not, pass common names.
        # Try common parameter names; this wrapper adapts.
        # First attempt: common modern API call signature
        try:
            return client.place_order(product_id=symbol, side=side, order_type=order_type, size=str(size))
        except TypeError:
            # fallback to alternate signature
            try:
                return client.place_order(product_id=symbol, side=side, size=str(size))
            except TypeError:
                # last resort: call with positional args
                return client.place_order(symbol, side, size, order_type)
    except Exception as e:
        logger.exception("Error placing order: %s", e)
        return None

# Expose a boolean to let other modules know if real client is active
REAL_CLIENT_ACTIVE = _client_ready

# Helpful log summary
if REAL_CLIENT_ACTIVE:
    logger.info("nija_client: Real Coinbase client ready. Live trading possible (if SANDBOX=False).")
else:
    logger.warning("nija_client: Real Coinbase client NOT ready. Running with DummyClient — no live trading will occur until coinbase_advanced_py import is fixed.")
