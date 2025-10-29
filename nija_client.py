# nija_client.py
import os
import sys
import shutil
import time
import logging
import importlib
import pkgutil
import inspect

# --- Configuration ---
VENV_SITE_PACKAGES = '/opt/render/project/src/.venv/lib/python3.13/site-packages'
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__) or ".")
SECRETS_DIR = "/opt/render/project/secrets"
COINBASE_PEM_PATH = os.environ.get("COINBASE_PEM_PATH", os.path.join(SECRETS_DIR, "coinbase.pem"))
COINBASE_PEM_CONTENT_ENV = "COINBASE_PEM_CONTENT"  # optional: base64/plain content written at startup
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_PASSPHRASE = os.environ.get("COINBASE_PASSPHRASE")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Ensure venv site-packages is prioritized (adjust if your path differs)
if VENV_SITE_PACKAGES not in sys.path:
    sys.path.insert(0, VENV_SITE_PACKAGES)

# --- Logging ---
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger("nija_client")

# --- Prevent local shadowing of installed package folders ---
SHADOW_CANDIDATES = ['coinbase_advanced_py', 'coinbase-advanced-py']

def backup_and_remove_local_shadow():
    moved = []
    for name in SHADOW_CANDIDATES:
        local_path = os.path.join(PROJECT_ROOT, name)
        if os.path.exists(local_path):
            ts = time.strftime("%Y%m%dT%H%M%S")
            backup_dir = os.path.join(PROJECT_ROOT, "local_shadow_backups", f"{ts}_{name}")
            os.makedirs(os.path.dirname(backup_dir), exist_ok=True)
            try:
                shutil.move(local_path, backup_dir)
                logger.warning("[NIJA] Moved local shadow folder %s -> %s", local_path, backup_dir)
                moved.append(local_path)
            except Exception as e:
                logger.error("[NIJA] Failed to move shadow folder %s: %s", local_path, e)
    return moved

try:
    moved = backup_and_remove_local_shadow()
    if moved:
        logger.info("[NIJA] Auto-fixed local shadow folders: %s", moved)
except Exception as e:
    logger.debug("[NIJA] Shadow fix skipped: %s", e)

# --- Dummy client fallback (safe, no live trades) ---
class DummyClient:
    def get_accounts(self):
        logger.warning("[DummyClient] get_accounts called - not live.")
        return []

    def place_order(self, *args, **kwargs):
        logger.warning("[DummyClient] place_order called - not live.")
        return {"status": "dummy"}

    # add any other methods your code expects from the real client
    def __repr__(self):
        return "<DummyClient>"

# --- Helper to write PEM from env var (use on Render if you store PEM as secret content) ---
def ensure_pem_on_disk():
    # If COINBASE_PEM_CONTENT is provided, write it to the target path (useful for Render secrets)
    pem_content = os.environ.get(COINBASE_PEM_CONTENT_ENV)
    if pem_content:
        try:
            os.makedirs(os.path.dirname(COINBASE_PEM_PATH), exist_ok=True)
            with open(COINBASE_PEM_PATH, "w", encoding="utf-8") as fh:
                fh.write(pem_content)
            os.chmod(COINBASE_PEM_PATH, 0o600)
            logger.info("[NIJA] Wrote PEM from env to %s", COINBASE_PEM_PATH)
            return True
        except Exception as e:
            logger.error("[NIJA] Failed to write PEM from env: %s", e)
            return False
    return os.path.exists(COINBASE_PEM_PATH)

# Try to ensure PEM (will create from env content if present)
pem_available = ensure_pem_on_disk()
if not pem_available:
    logger.warning("[NIJA] PEM file not found at %s and COINBASE_PEM_CONTENT not provided.", COINBASE_PEM_PATH)

# --- Try to import and instantiate live Coinbase client (PEM-based preferred) ---
CoinbaseClient = None
client = None

try:
    # Prefer the PEM-based client if available
    # coinbase_advanced_py.client.CoinbaseClient typically accepts api_key, pem_file_path, passphrase
    m = importlib.import_module("coinbase_advanced_py.client")
    if hasattr(m, "CoinbaseClient"):
        CoinbaseClient = getattr(m, "CoinbaseClient")
        logger.info("[NIJA] coinbase_advanced_py.client.CoinbaseClient available.")
except ModuleNotFoundError:
    logger.debug("[NIJA] coinbase_advanced_py.client module not found; will try other locations.")
except Exception as e:
    logger.debug("[NIJA] Error importing coinbase client module: %s", e)

# fallback: scan some likely modules (defensive)
if CoinbaseClient is None:
    candidates = [
        "coinbase_advanced_py.client",
        "coinbase_advanced_py",
        "coinbase",
        "coinbase.rest",
        "coinbase.client",
    ]
    for c in candidates:
        try:
            M = importlib.import_module(c)
            for name, val in vars(M).items():
                if name == "CoinbaseClient" and inspect.isclass(val):
                    CoinbaseClient = val
                    logger.info("[NIJA] Found CoinbaseClient in module: %s", c)
                    break
            if CoinbaseClient:
                break
        except Exception:
            continue

# Instantiate
if CoinbaseClient and pem_available and COINBASE_API_KEY:
    try:
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            pem_file_path=COINBASE_PEM_PATH,
            passphrase=COINBASE_PASSPHRASE
        )
        logger.info("[NIJA] Live CoinbaseClient instantiated successfully (PEM).")
    except TypeError as te:
        # handle clients that don't accept passphrase/pem_file_path signature
        logger.warning("[NIJA] Failed to init CoinbaseClient with PEM (signature mismatch): %s", te)
        try:
            # try alternate constructor names/args if present
            client = CoinbaseClient(COINBASE_API_KEY, COINBASE_PEM_PATH)
            logger.info("[NIJA] Live CoinbaseClient instantiated with positional args.")
        except Exception as e:
            logger.error("[NIJA] Failed to instantiate CoinbaseClient: %s", e)
            client = DummyClient()
    except Exception as e:
        logger.error("[NIJA] Failed to instantiate CoinbaseClient: %s", e)
        client = DummyClient()
else:
    if not CoinbaseClient:
        logger.warning("[NIJA] CoinbaseClient class not located in installed packages.")
    if not pem_available:
        logger.warning("[NIJA] PEM not available; cannot instantiate PEM-based client.")
    if not COINBASE_API_KEY:
        logger.warning("[NIJA] COINBASE_API_KEY not set.")
    client = DummyClient()

logger.info("[NIJA] Using client: %s", type(client).__name__)
logger.info("[NIJA] SANDBOX=%s", os.environ.get("SANDBOX", "None"))

# --- Exports / utility functions ---
def get_accounts():
    return client.get_accounts()

def place_order(*args, **kwargs):
    return client.place_order(*args, **kwargs)

def check_live_status():
    """
    Returns True if live Coinbase client appears to be usable (returns accounts).
    Always returns False for DummyClient.
    """
    if isinstance(client, DummyClient):
        logger.warning("[NIJA] Trading not live (DummyClient active)")
        return False
    try:
        accounts = client.get_accounts()
        if accounts:
            logger.info("[NIJA] ✅ Live trading ready")
            return True
        else:
            logger.warning("[NIJA] No accounts returned by Coinbase client")
            return False
    except Exception as e:
        # common PEM / key errors will surface here; log them but do not raise to avoid process crash
        logger.warning("[NIJA] Exception checking live status: %s", e)
        return False

# --- Automatic startup live check (runs on import) ---
def startup_live_check():
    print("=== NIJA STARTUP LIVE CHECK ===")
    logger.info("[NIJA] Performing startup live check...")
    live = check_live_status()
    if live:
        logger.info("[NIJA] ✅ Nija trading is LIVE!")
        print("✅ NIJA is live! Ready to trade.")
    else:
        logger.warning("[NIJA] ❌ Nija trading is NOT live — using DummyClient")
        print("❌ NIJA is NOT live — using DummyClient")

startup_live_check()

# allow script to be used interactively
if __name__ == "__main__":
    import json
    print(json.dumps({
        "client": type(client).__name__,
        "live": check_live_status(),
        "pem_path": COINBASE_PEM_PATH,
    }, indent=2))
