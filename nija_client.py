# nija_client.py
import os
import logging

# --- Logging setup ---
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
logger = logging.getLogger("nija_client")

# --- DummyClient fallback ---
class DummyClient:
    def get_accounts(self):
        logger.warning("[DummyClient] get_accounts called - no live trading!")
        return []

    def place_order(self, *args, **kwargs):
        logger.warning("[DummyClient] place_order called - no live trading!")
        return {"status": "dummy"}

# --- Attempt CoinbaseClient import ---
CoinbaseClient = None
try:
    import sys
    # Remove local shadowing
    if "coinbase_advanced_py.client" not in sys.modules:
        from coinbase_advanced_py.client import CoinbaseClient
        logger.info("[NIJA] Successfully imported CoinbaseClient")
except ModuleNotFoundError as e:
    logger.warning(f"[NIJA] CoinbaseClient not found. Using DummyClient. ({e})")
except Exception as e:
    logger.warning(f"[NIJA] CoinbaseClient import error. Using DummyClient. ({e})")
    CoinbaseClient = None

# --- Check if live trading can be used ---
def can_use_live_client():
    required_keys = ["COINBASE_API_KEY", "COINBASE_API_SECRET"]
    missing = [k for k in required_keys if not os.environ.get(k)]
    if missing:
        logger.warning(f"[NIJA] Missing Coinbase API keys: {missing}")
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
        logger.warning(f"[NIJA] Failed to instantiate CoinbaseClient: {e}. Using DummyClient instead.")
        client = DummyClient()
else:
    client = DummyClient()
    logger.info("[NIJA] Using DummyClient (live CoinbaseClient unavailable or API keys missing)")

# --- Safe client type logging ---
client_name = type(client).__name__ if client else "UnknownClient"
logger.info(f"[NIJA] Using client: {client_name}")
logger.info(f"[NIJA] SANDBOX={os.environ.get('SANDBOX', 'None')}")

# --- Helper functions for live trading ---
def get_accounts():
    return client.get_accounts()

def place_order(*args, **kwargs):
    return client.place_order(*args, **kwargs)

# --- Diagnostic for live readiness ---
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
            logger.warning("[NIJA] No accounts returned")
            print("❌ NIJA cannot access accounts")
            return False
    except Exception as e:
        logger.warning(f"[NIJA] Exception checking live status: {e}")
        print(f"❌ NIJA live check failed: {e}")
        return False

# --- Run diagnostic on import ---
if __name__ == "__main__":
    check_live_status()
