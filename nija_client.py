# nija_client.py
import os
import logging

# --- Logging Setup ---
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
logger = logging.getLogger("nija_client")

# --- Try importing CoinbaseClient ---
CoinbaseClient = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] Successfully imported CoinbaseClient")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not installed. Using DummyClient instead.")
except Exception as e:
    logger.warning(f"[NIJA] Error importing CoinbaseClient: {e}")

# --- Dummy client as fallback ---
class DummyClient:
    def get_accounts(self):
        logger.warning("[DummyClient] get_accounts called - no live trading!")
        return []

    def place_order(self, *args, **kwargs):
        logger.warning("[DummyClient] place_order called - no live trading!")
        return {"status": "dummy"}

# --- Function to check if live trading is possible ---
def can_use_live_client():
    required_keys = ["COINBASE_API_KEY", "COINBASE_API_SECRET"]
    missing_keys = [k for k in required_keys if not os.environ.get(k)]
    if missing_keys:
        logger.warning(f"[NIJA] Missing Coinbase API keys: {missing_keys}")
        return False
    return True

# --- Instantiate the appropriate client ---
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
    if CoinbaseClient:
        logger.info("[NIJA] CoinbaseClient exists but API keys missing. Using DummyClient.")
    else:
        logger.info("[NIJA] CoinbaseClient unavailable. Using DummyClient.")

logger.info(f"[NIJA] Using client: {'CoinbaseClient' if isinstance(client, CoinbaseClient) else 'DummyClient'}")
logger.info(f"[NIJA] SANDBOX={os.environ.get('SANDBOX', 'None')}")

# --- Optional health check method ---
def health_check():
    try:
        accounts = client.get_accounts()
        return {"status": "ok", "accounts": len(accounts)}
    except Exception as e:
        return {"status": "error", "message": str(e)}
