# nija_client.py

import os
from coinbase_advanced_py.client import CoinbaseClient

# Use secret PEM path if available
COINBASE_PEM_PATH = "/opt/render/project/secrets/coinbase.pem"
API_KEY = os.environ.get("COINBASE_API_KEY")
PASSPHRASE = os.environ.get("COINBASE_PASSPHRASE")  # if needed

if not os.path.exists(COINBASE_PEM_PATH):
    raise FileNotFoundError(f"Coinbase PEM not found at {COINBASE_PEM_PATH}")

client = CoinbaseClient(
    api_key=API_KEY,
    pem_file_path=COINBASE_PEM_PATH,
    passphrase=PASSPHRASE
)

import os
import logging
from coinbase.rest import RESTClient  # Use RESTClient for live trading

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Instantiate live client ---
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET_PATH = os.getenv("COINBASE_API_SECRET")
COINBASE_PASSPHRASE = os.getenv("COINBASE_PASSPHRASE")
SANDBOX = os.getenv("SANDBOX")  # None for live

try:
    client = RESTClient(
        key=COINBASE_API_KEY,
        secret_path=COINBASE_API_SECRET_PATH,
        passphrase=COINBASE_PASSPHRASE,
        sandbox=SANDBOX is not None
    )
    logger.info("[NIJA] Live client instantiated via RESTClient")
except Exception as e:
    logger.warning("[NIJA] Could not instantiate live client: %s", e)
    from nija_client_dummy import DummyClient  # fallback
    client = DummyClient()

# --- Exports ---
def get_accounts():
    return client.get_accounts()

def place_order(*args, **kwargs):
    return client.place_order(*args, **kwargs)

def check_live_status():
    if not client or "DummyClient" in str(type(client)):
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
            logger.warning("[NIJA] No accounts returned by RESTClient")
            print("❌ NIJA cannot access accounts")
            return False
    except Exception as e:
        logger.warning("[NIJA] Exception checking live status: %s", e)
        print(f"❌ NIJA live check failed: {e}")
        return False

# --- Automatic startup check ---
def startup_live_check():
    print("=== NIJA STARTUP LIVE CHECK ===")
    logger.info("[NIJA] Performing startup live check...")
    check_live_status()

startup_live_check()

if __name__ == "__main__":
    check_live_status()
