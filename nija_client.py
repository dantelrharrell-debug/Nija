# nija_client.py
import os
import logging
from decimal import Decimal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Dummy client fallback ---
class DummyClient:
    def __init__(self):
        logger.warning("[DummyClient] Using simulation mode — no live trades")

    def get_accounts(self):
        return [{"currency": "USD", "balance": "10000.00"}]

    def get_spot_account_balances(self):
        return [{"currency": "USD", "balance": "10000.00"}]

    def place_order(self, *args, **kwargs):
        logger.info(f"[DummyClient] Simulated order: {kwargs}")
        return {"status": "simulated", "order": kwargs}

# --- Correct import path for CoinbaseClient ---
CoinbaseClient = None
try:
    from coinbase_advanced_py import CoinbaseClient
    logger.info("[NIJA] CoinbaseClient imported successfully")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not available. Using DummyClient")

# --- Auth detection ---
def init_coinbase_client():
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    api_passphrase = os.getenv("COINBASE_API_PASSPHRASE")

    if not api_key or not api_secret:
        logger.error("[FAIL] Missing COINBASE_API_KEY or COINBASE_API_SECRET.")
        return DummyClient()

    # Try Advanced Trade API (no passphrase)
    try:
        client = CoinbaseClient(api_key=api_key, api_secret=api_secret)
        logger.info("[NIJA] Initialized Advanced Trade API client (no passphrase)")
        return client
    except Exception as e:
        logger.warning(f"[NIJA] Advanced Trade init failed: {e}")

    # Fallback to legacy (with passphrase)
    if api_passphrase:
        try:
            client = CoinbaseClient(api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase)
            logger.info("[NIJA] Initialized Legacy API client (with passphrase)")
            return client
        except Exception as e:
            logger.error(f"[NIJA] Legacy API init failed: {e}")

    logger.error("[FAIL] Could not initialize any Coinbase client. Using DummyClient.")
    return DummyClient()

client = init_coinbase_client()

# --- Helper ---
def get_usd_balance(client):
    try:
        if hasattr(client, "get_spot_account_balances"):
            balances = client.get_spot_account_balances()
        else:
            balances = client.get_accounts()
        for b in balances:
            if b["currency"] == "USD":
                return Decimal(b["balance"])
    except Exception as e:
        logger.error(f"[Balance fetch error] {e}")
    return Decimal(0)
