# nija_client.py
import sys
import os
import logging
import shutil
import time
import importlib
import pkgutil
import inspect

# --- Ensure virtualenv site-packages is prioritized (adjust path if your venv path differs) ---
VENV_SITE_PACKAGES = '/opt/render/project/src/.venv/lib/python3.13/site-packages'
if VENV_SITE_PACKAGES not in sys.path:
    sys.path.insert(0, VENV_SITE_PACKAGES)

# --- Logging setup ---
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
logger = logging.getLogger("nija_client")

# --- Project root and shadowing candidates ---
project_root = os.path.abspath(os.path.dirname(__file__) or ".")
shadow_candidates = ['coinbase_advanced_py', 'coinbase-advanced-py']

def backup_and_remove_local_shadow():
    found = []
    for name in shadow_candidates:
        local_path = os.path.join(project_root, name)
        if os.path.exists(local_path):
            local_path_abs = os.path.abspath(local_path)
            if not local_path_abs.startswith(project_root):
                logger.warning("[NIJA] Skipping suspicious path not in project root: %s", local_path_abs)
                continue
            ts = time.strftime("%Y%m%dT%H%M%S")
            backup_dir = os.path.join(project_root, "local_shadow_backups", f"{ts}_{name}")
            os.makedirs(os.path.dirname(backup_dir), exist_ok=True)
            try:
                shutil.move(local_path_abs, backup_dir)
                logger.warning("[NIJA] Moved local shadow folder %s -> %s", local_path_abs, backup_dir)
                found.append(local_path_abs)
            except Exception as e:
                logger.error("[NIJA] Failed to move shadow folder %s: %s", local_path_abs, e)
    return found

moved = backup_and_remove_local_shadow()
if moved:
    logger.info("[NIJA] Auto-fixed local shadow folders: %s", moved)

# --- DummyClient fallback ---
class DummyClient:
    def get_accounts(self):
        logger.warning("[DummyClient] get_accounts called - no live trading!")
        return []

    def place_order(self, *args, **kwargs):
        logger.warning("[DummyClient] place_order called - no live trading!")
        return {"status": "dummy"}

# --- Helper: try_import_candidates and scan for CoinbaseClient symbol ---
def try_import_candidates(candidates):
    """
    Try import candidate module paths and return the module that contains CoinbaseClient.
    Returns tuple (module, symbol_name) or (None, None).
    """
    for mod_path in candidates:
        try:
            logger.info("[NIJA] Trying import: %s", mod_path)
            m = importlib.import_module(mod_path)
            # scan module attributes for CoinbaseClient
            for name, val in vars(m).items():
                if name == "CoinbaseClient" and inspect.isclass(val):
                    logger.info("[NIJA] Found CoinbaseClient in %s (attribute %s)", mod_path, name)
                    return m, name
            # also try to search submodules if pkg
            if hasattr(m, "__path__"):
                for finder, subname, ispkg in pkgutil.iter_modules(m.__path__):
                    candidate_sub = f"{mod_path}.{subname}"
                    try:
                        ms = importlib.import_module(candidate_sub)
                        if hasattr(ms, "CoinbaseClient") and inspect.isclass(getattr(ms, "CoinbaseClient")):
                            logger.info("[NIJA] Found CoinbaseClient in %s (attribute CoinbaseClient)", candidate_sub)
                            return ms, "CoinbaseClient"
                    except Exception:
                        continue
        except ModuleNotFoundError as e:
            logger.debug("[NIJA] Module not found: %s (%s)", mod_path, e)
        except Exception as e:
            logger.debug("[NIJA] Error importing %s: %s", mod_path, e)
    return None, None

# --- Candidate module paths to try (ordered) ---
candidates = [
    "coinbase_advanced_py.client",
    "coinbase_advanced_py.clients",
    "coinbase_advanced_py.api.client",
    "coinbase_advanced_py.api",
    "coinbase_advanced_py",
    "coinbase",
    "coinbase.client",
    "coinbase_advanced_py.client_api",
    "coinbase_advanced_py._client",
]

# Try to locate CoinbaseClient across candidates
found_module, found_symbol = try_import_candidates(candidates)

CoinbaseClient = None
if found_module and found_symbol:
    try:
        CoinbaseClient = getattr(found_module, found_symbol)
        logger.info("[NIJA] Will use CoinbaseClient from module: %s (symbol: %s)", found_module.__name__, found_symbol)
    except Exception as e:
        logger.warning("[NIJA] Found symbol but failed to bind: %s", e)

# As a last resort, search for symbol textual occurrences under venv site-packages
def search_for_symbol_text(root, symbol="CoinbaseClient", max_files=200):
    matches = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            try:
                count += 1
                if count > max_files:
                    return matches
                p = os.path.join(dirpath, fn)
                with open(p, "r", encoding="utf-8", errors="ignore") as fh:
                    txt = fh.read()
                    if symbol in txt:
                        matches.append(os.path.relpath(p, root))
            except Exception:
                continue
    return matches

if CoinbaseClient is None:
    # attempt textual search (cheap snapshot) to show likely locations in logs
    try:
        vroot = VENV_SITE_PACKAGES
        if os.path.exists(vroot):
            finds = search_for_symbol_text(vroot, "CoinbaseClient", max_files=1000)
            if finds:
                logger.info("[NIJA] Textual search found CoinbaseClient referenced in files: %s", finds[:20])
            else:
                logger.info("[NIJA] Textual search did NOT find CoinbaseClient in venv site-packages")
        else:
            logger.info("[NIJA] VENV site-packages path does not exist: %s", vroot)
    except Exception as e:
        logger.debug("[NIJA] Textual search failed: %s", e)

# --- Check environment readiness ---
def can_use_live_client():
    required_keys = ["COINBASE_API_KEY", "COINBASE_API_SECRET"]
    missing = [k for k in required_keys if not os.environ.get(k)]
    if missing:
        logger.warning("[NIJA] Missing Coinbase API keys: %s", missing)
        return False
    return True

# --- Instantiate client safely (if found) ---
client = None
if CoinbaseClient and can_use_live_client():
    try:
        client = CoinbaseClient(
            api_key=os.environ["COINBASE_API_KEY"],
            api_secret=os.environ["COINBASE_API_SECRET"],
            sandbox=os.environ.get("SANDBOX", "False").lower() == "true"
        )
        logger.info("[NIJA] Live CoinbaseClient instantiated successfully from located symbol")
    except Exception as e:
        logger.warning("[NIJA] Failed to instantiate CoinbaseClient: %s. Using DummyClient instead.", e)
        client = DummyClient()
else:
    client = DummyClient()
    logger.info("[NIJA] Using DummyClient (CoinbaseClient not located or API keys missing)")

# --- Logging final status ---
client_name = type(client).__name__ if client else "UnknownClient"
logger.info("[NIJA] Using client: %s", client_name)
logger.info("[NIJA] SANDBOX=%s", os.environ.get('SANDBOX', 'None'))

# --- Exports ---
def get_accounts():
    return client.get_accounts()

def place_order(*args, **kwargs):
    return client.place_order(*args, **kwargs)

def check_live_status():
    if isinstance(client, DummyClient):
        logger.warning("[NIJA] Trading not live (DummyClient active)")
        print("❌ NIJA is NOT live — using DummyClient")
        return False
    try:
        accounts = client.get_accounts()
        if accounts:
            logger.info("[NIJA] ✅ Live trading ready")
            print("✅ NIJA is live! Ready to trade.")
            return True
        else:
            logger.warning("[NIJA] No accounts returned by CoinbaseClient")
            print("❌ NIJA cannot access accounts")
            return False
    except Exception as e:
        logger.warning("[NIJA] Exception checking live status: %s", e)
        print(f"❌ NIJA live check failed: {e}")
        return False

if __name__ == "__main__":
    check_live_status()
