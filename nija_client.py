# nija_client.py
import logging
from decimal import Decimal

# --- Logging setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Safe DummyClient ---
class DummyClient:
    def get_accounts(self):
        # Always return a safe USD balance
        logger.warning("[DummyClient] Returning simulated account balances")
        return [{"currency": "USD", "balance": "10000.00"}]

    def get_spot_account_balances(self):
        return [{"currency": "USD", "balance": "10000.00"}]

    def place_order(self, *args, **kwargs):
        logger.info(f"[DummyClient] Simulated order: {kwargs}")
        return {"status": "simulated", "order": kwargs}

# --- Initialize client safely ---
def init_coinbase_client():
    logger.warning("[NIJA] CoinbaseClient unavailable. Using DummyClient for safety.")
    return DummyClient()

# --- Create global client instance ---
client = init_coinbase_client()

# --- Helper to get USD balance ---
def get_usd_balance(client):
    try:
        if hasattr(client, "get_spot_account_balances"):
            accounts = client.get_spot_account_balances()
        else:
            accounts = client.get_accounts()
        for acc in accounts:
            if acc.get("currency") == "USD":
                return Decimal(acc.get("balance", "0"))
    except Exception as e:
        logger.warning(f"[NIJA-DEBUG] Could not fetch balances: {e}")
    return Decimal("0")
