# nija_client.py
import os
import logging

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Load environment variables ---
DRY_RUN = os.getenv("DRY_RUN", "False").lower() == "true"
LIVE_TRADING = os.getenv("LIVE_TRADING", "False").lower() == "true"

# --- Initialize Coinbase client or DummyClient ---
client = None
try:
    from coinbase_advanced_py.client import CoinbaseClient

    # Ensure PEM path exists if provided
    pem_path = os.getenv("COINBASE_PEM_PATH")
    if pem_path and not os.path.exists(pem_path):
        logger.warning(f"[NIJA] PEM file not found at {pem_path}")

    client = CoinbaseClient(
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET"),
        passphrase=os.getenv("COINBASE_PASSPHRASE"),
        pem_path=pem_path
    )
    logger.info("[NIJA] CoinbaseClient loaded successfully")

except Exception as e:
    logger.warning(f"[NIJA] CoinbaseClient not available; using DummyClient. Error: {e}")
    try:
        from nija_client_dummy import DummyClient
        client = DummyClient()
    except Exception as dummy_error:
        logger.error(f"[NIJA] DummyClient could not be loaded: {dummy_error}")
        raise

logger.info(f"[NIJA] Module loaded. DRY_RUN={DRY_RUN} LIVE_TRADING={LIVE_TRADING} client_is_dummy={isinstance(client, type('DummyClient', (), {}))}")

# --- Example helper functions using client ---
def get_account_balance():
    if client is None:
        logger.error("[NIJA] No client available to fetch balance")
        return None
    try:
        return client.get_accounts()  # adjust per CoinbaseClient API
    except Exception as e:
        logger.error(f"[NIJA] Error fetching accounts: {e}")
        return None

def place_order(order_type, amount, currency="USD"):
    if DRY_RUN or not LIVE_TRADING:
        logger.info(f"[NIJA] DRY_RUN: would place {order_type} order for {amount} {currency}")
        return None
    try:
        return client.place_order(order_type, amount, currency)  # adjust per CoinbaseClient API
    except Exception as e:
        logger.error(f"[NIJA] Error placing order: {e}")
        return None
