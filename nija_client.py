# nija_client.py
import sys
import os
import logging
import shutil
import time

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
    """
    If local folders with names that shadow the installed package exist in the project root,
    move them into a timestamped backup directory inside the project (local_shadow_backups/).
    This is safer than deleting outright and prevents Python from importing the wrong package.
    """
    found = []
    for name in shadow_candidates:
        local_path = os.path.join(project_root, name)
        if os.path.exists(local_path):
            # Safety check: ensure the path is inside project_root
            local_path_abs = os.path.abspath(local_path)
            if not local_path_abs.startswith(project_root):
                logger.warning("[NIJA] Skipping suspicious path not in project root: %s", local_path_abs)
                continue

            # Create backup dir
            ts = time.strftime("%Y%m%dT%H%M%S")
            backup_dir = os.path.join(project_root, "local_shadow_backups", f"{ts}_{name}")
            os.makedirs(os.path.dirname(backup_dir), exist_ok=True)
            try:
                shutil.move(local_path_abs, backup_dir)
                logger.warning("[NIJA] Moved local shadow folder %s -> %s (to avoid shadowing installed package)", local_path_abs, backup_dir)
                found.append(local_path_abs)
            except Exception as e:
                logger.error("[NIJA] Failed to move shadow folder %s: %s", local_path_abs, e)
    return found

# Run the auto-fix (safe backup + move) immediately — only affects project-root folders named above.
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

# --- Attempt CoinbaseClient import (safe) ---
CoinbaseClient = None
try:
    # import after ensuring site-packages precedence and after possible shadow move
    from coinbase_advanced_py.client import CoinbaseClient  # type: ignore
    logger.info("[NIJA] Successfully imported coinbase_advanced_py.client.CoinbaseClient")
except ModuleNotFoundError as e:
    logger.warning("[NIJA] CoinbaseClient not found. Using DummyClient. (%s)", e)
except Exception as e:
    logger.warning("[NIJA] CoinbaseClient import error. Using DummyClient. (%s)", e)

# --- Check API keys ---
def can_use_live_client():
    required_keys = ["COINBASE_API_KEY", "COINBASE_API_SECRET"]
    missing = [k for k in required_keys if not os.environ.get(k)]
    if missing:
        logger.warning("[NIJA] Missing Coinbase API keys: %s", missing)
        return False
    return True

# --- Instantiate client safely ---
client = None
if CoinbaseClient and can_use_live_client():
    try:
        client = CoinbaseClient(
            api_key=os.environ["COINBASE_API_KEY"],
            api_secret=os.environ["COINBASE_API_SECRET"],
            sandbox=os.environ.get("SANDBOX", "False").lower() == "true"
        )
        logger.info("[NIJA] Live CoinbaseClient instantiated successfully")
    except Exception as e:
        logger.warning("[NIJA] Failed to instantiate CoinbaseClient: %s. Using DummyClient instead.", e)
        client = DummyClient()
else:
    client = DummyClient()
    logger.info("[NIJA] Using DummyClient (live CoinbaseClient unavailable or API keys missing)")

# --- Safe client type logging ---
client_name = type(client).__name__ if client else "UnknownClient"
logger.info("[NIJA] Using client: %s", client_name)
logger.info("[NIJA] SANDBOX=%s", os.environ.get('SANDBOX', 'None'))

# --- Helper functions exported to other modules ---
def get_accounts():
    return client.get_accounts()

def place_order(*args, **kwargs):
    return client.place_order(*args, **kwargs)

# --- Live diagnostic ---
def check_live_status():
    """
    Returns True if live Coinbase client is active and returns accounts.
    Prints friendly status output.
    """
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

# --- If executed directly, run the diagnostic ---
if __name__ == "__main__":
    check_live_status()
