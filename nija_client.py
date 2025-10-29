# nija_client.py
import os
import shutil
import logging

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Clean up duplicate Coinbase local folders that shadow pip package ---
for name in ("coinbase_advanced_py", "coinbase-advanced-py"):
    folder = os.path.join(os.getcwd(), name)
    if os.path.isdir(folder):
        backup = os.path.join(os.getcwd(), "local_shadow_backups", name)
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        try:
            shutil.move(folder, backup)
            logger.warning(f"[NIJA] Moved local shadow folder {folder} -> {backup}")
        except Exception as e:
            logger.error(f"[NIJA] Failed to move shadow folder {folder}: {e}")

# --- Try to import CoinbaseClient and initialize from environment ---
client = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] coinbase_advanced_py imported from pip")
    API_KEY = os.getenv("COINBASE_API_KEY")
    API_SECRET = os.getenv("COINBASE_API_SECRET")           # if you use content-paste option
    API_SECRET_PATH = os.getenv("COINBASE_API_SECRET_PATH") # preferred: secret file path
    API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
    SANDBOX = os.getenv("SANDBOX", "true").lower() in ("1", "true", "yes")

    # Load PEM content if path provided (preferred)
    if not API_SECRET and API_SECRET_PATH:
        try:
            with open(API_SECRET_PATH, "r") as f:
                API_SECRET = f.read()
        except Exception as e:
            logger.error(f"[NIJA] Could not read PEM file at {API_SECRET_PATH}: {e}")

    if not all([API_KEY, API_SECRET]):
        raise ValueError("COINBASE_API_KEY and COINBASE_API_SECRET (or COINBASE_API_SECRET_PATH) required")

    # Initialize client (adjust constructor args to the version you use)
    client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, api_passphrase=API_PASSPHRASE, sandbox=SANDBOX)
    logger.info("[NIJA] ✅ CoinbaseClient initialized -> Live trading ENABLED")

except ModuleNotFoundError:
    logger.warning("[NIJA] coinbase_advanced_py not installed in venv. Running with DummyClient.")
except ValueError as ve:
    logger.warning(f"[NIJA] Coinbase keys missing: {ve}. Running with DummyClient.")
except Exception as e:
    logger.warning(f"[NIJA] CoinbaseClient initialization failed: {e}. Running with DummyClient.")

# --- Dummy client fallback ---
class DummyClient:
    def place_order(self, **kwargs):
        logger.info(f"[DUMMY] Simulated order -> {kwargs}")
        return {"id": "SIMULATED", "status": "simulated", **kwargs}

    def get_account(self, *args, **kwargs):
        return {"balance": "0"}

if client is None:
    client = DummyClient()
    logger.info("[NIJA] DummyClient attached -> simulated trading active")
