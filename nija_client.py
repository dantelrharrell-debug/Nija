# nija_client.py
import os
import logging
from decimal import Decimal
import time

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Load environment variables ---
from dotenv import load_dotenv
load_dotenv()  # loads .env automatically

LIVE_TRADING = os.getenv("LIVE_TRADING", "False").lower() in ["true", "1"]
DRY_RUN = os.getenv("DRY_RUN", "True").lower() in ["true", "1"]

# --- Load Coinbase PEM ---
COINBASE_PEM_PATH = "/opt/render/project/secrets/coinbase.pem"
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_PASSPHRASE = os.getenv("COINBASE_PASSPHRASE")

# --- DummyClient as fallback ---
class DummyClient:
    def __init__(self):
        logger.warning("[NIJA] Using DummyClient — no real trades will execute.")

    def get_accounts(self):
        return [{"currency": "USD", "balance": "1000"}]

    def place_order(self, *args, **kwargs):
        logger.info(f"[NIJA DummyClient] Simulated order: {args}, {kwargs}")
        return {"id": "dummy_order"}

# --- Try to import CoinbaseClient ---
CoinbaseClient = None
client = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    if all([COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_PASSPHRASE, os.path.exists(COINBASE_PEM_PATH)]):
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            passphrase=COINBASE_PASSPHRASE,
            pem_path=COINBASE_PEM_PATH
        )
        logger.info("[NIJA] CoinbaseClient initialized successfully ✅")
    else:
        logger.warning("[NIJA] Coinbase credentials or PEM missing — falling back to DummyClient")
        client = DummyClient()
except ModuleNotFoundError:
    logger.warning("[NIJA] coinbase_advanced_py not found; using DummyClient")
    client = DummyClient()

logger.info(f"[NIJA] Module loaded. DRY_RUN={DRY_RUN} LIVE_TRADING={LIVE_TRADING} client_is_dummy={isinstance(client, DummyClient)}")
