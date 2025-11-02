import os
import logging
from decimal import Decimal

# ----------------------
# Configure logger
# ----------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_preflight")

# ----------------------
# Environment check
# ----------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

if not API_KEY or not API_SECRET:
    logger.error("❌ Missing Coinbase API credentials! Trading will run in SIMULATED mode.")
else:
    logger.info("✅ Coinbase API credentials detected. Ready for LIVE trading.")
    logger.info(f"[DEBUG] API_SECRET len={len(API_SECRET)} first/last 4: {API_SECRET[:4]}...{API_SECRET[-4:]}")

# ----------------------
# Dummy client fallback
# ----------------------
class DummyClient:
    def __init__(self):
        logger.info("[NIJA] Using DummyClient (SIMULATED trading).")
        self.name = "DummyClient"

    def place_buy(self, product_id, amount):
        logger.info(f"[DummyClient] Simulated BUY {{'product_id': {product_id}, 'amount': {amount}}}")
        return {"status": "simulated", "product_id": product_id, "amount": amount}

    def place_sell(self, product_id, amount):
        logger.info(f"[DummyClient] Simulated SELL {{'product_id': {product_id}, 'amount': {amount}}}")
        return {"status": "simulated", "product_id": product_id, "amount": amount}

    def get_usd_balance(self) -> Decimal:
        return Decimal("100.00")  # Fixed simulated balance

# ----------------------
# Try importing real Coinbase client
# ----------------------
CoinbaseClient = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] Successfully imported CoinbaseClient")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not available. Using DummyClient instead.")
except Exception as e:
    logger.error(f"[NIJA] Unexpected error importing CoinbaseClient: {e}")

# ----------------------
# Initialize client
# ----------------------
def init_client():
    if not (API_KEY and API_SECRET):
        logger.warning("[NIJA] Missing API key/secret — using DummyClient")
        return DummyClient()

    try:
        client = CoinbaseClient(API_KEY, API_SECRET)
        logger.info("[NIJA] Authenticated with CoinbaseClient successfully.")
        return client
    except Exception as e:
        logger.error(f"[NIJA] Failed to authenticate CoinbaseClient: {e}")
        return DummyClient()

# ----------------------
# Helper: fetch USD balance
# ----------------------
def get_usd_balance(client):
    try:
        if hasattr(client, "get_usd_balance"):
            return client.get_usd_balance()
        if hasattr(client, "get_account_balance"):
            return client.get_account_balance()
    except Exception as e:
        logger.exception(f"[NIJA] Error fetching USD balance: {e}")
    return Decimal("0")

# ----------------------
# Preflight check
# ----------------------
if __name__ == "__main__":
    client = init_client()
    balance = get_usd_balance(client)
    mode = "LIVE" if isinstance(client, CoinbaseClient) else "SIMULATED"
    logger.info(f"[PRE-FLIGHT] Mode: {mode}, USD balance: {balance}")
