# nija_client.py

import os
import logging
from coinbase_advanced_py.client import CoinbaseClient

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Coinbase credentials ---
COINBASE_PEM_PATH = "/opt/render/project/secrets/coinbase.pem"
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
SANDBOX = os.getenv("SANDBOX")  # Optional: use sandbox if set

# --- Ensure PEM exists ---
if not os.path.exists(COINBASE_PEM_PATH):
    logger.warning(f"[NIJA] Coinbase PEM not found at {COINBASE_PEM_PATH}. Using DummyClient.")
    from nija_client_dummy import DummyClient
    client = DummyClient()
else:
    try:
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            pem_file_path=COINBASE_PEM_PATH,
            sandbox=SANDBOX is not None
        )
        logger.info("[NIJA] ✅ CoinbaseClient initialized successfully")
    except Exception as e:
        logger.warning(f"[NIJA] Failed to initialize CoinbaseClient: {e}")
        from nija_client_dummy import DummyClient
        client = DummyClient()

# --- Helper functions ---
def get_accounts():
    try:
        return client.get_accounts()
    except Exception as e:
        logger.warning(f"[NIJA] get_accounts failed: {e}")
        return None

def place_order(*args, **kwargs):
    try:
        return client.place_order(*args, **kwargs)
    except Exception as e:
        logger.warning(f"[NIJA] place_order failed: {e}")
        return None

def check_live_status():
    if "DummyClient" in str(type(client)):
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
        logger.warning(f"[NIJA] Exception checking live status: {e}")
        print(f"❌ NIJA live check failed: {e}")
        return False

# --- Startup check ---
def startup_live_check():
    print("=== NIJA STARTUP LIVE CHECK ===")
    logger.info("[NIJA] Performing startup live check...")
    check_live_status()

startup_live_check()

if __name__ == "__main__":
    check_live_status()
