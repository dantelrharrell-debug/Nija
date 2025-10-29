import os
import logging

# -------------------------------
# Setup logging
# -------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# -------------------------------
# Load live trading flag
# -------------------------------
LIVE_TRADING = os.environ.get("LIVE_TRADING", "0") == "1"
DRY_RUN = os.environ.get("DRY_RUN", "1") == "1"

# -------------------------------
# Try importing CoinbaseClient
# -------------------------------
CoinbaseClient = None
client_is_dummy = False
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] coinbase_advanced_py imported successfully")
except ModuleNotFoundError:
    logger.warning("[NIJA] coinbase_advanced_py not found; using DummyClient")
    CoinbaseClient = None

# -------------------------------
# Check for required environment keys
# -------------------------------
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_PASSPHRASE = os.environ.get("COINBASE_PASSPHRASE")
COINBASE_PEM_PATH = os.environ.get(
    "COINBASE_PEM_PATH", "/opt/render/project/secrets/coinbase.pem"
)

# -------------------------------
# Initialize client
# -------------------------------
if LIVE_TRADING and CoinbaseClient and COINBASE_API_KEY and COINBASE_API_SECRET and COINBASE_PASSPHRASE:
    try:
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            api_secret=COINBASE_API_SECRET,
            passphrase=COINBASE_PASSPHRASE,
            pem_file=COINBASE_PEM_PATH
        )
        logger.info("[NIJA] CoinbaseClient initialized — LIVE TRADING ENABLED ✅")
    except Exception as e:
        logger.error(f"[NIJA] Failed to initialize CoinbaseClient: {e}")
        client_is_dummy = True
else:
    # Fallback to DummyClient
    class DummyClient:
        def get_accounts(self):
            return []

        def place_order(self, *args, **kwargs):
            logger.info(f"[NIJA][DUMMY] Pretending to place order: {args}, {kwargs}")
            return {}

    client = DummyClient()
    client_is_dummy = True
    if LIVE_TRADING:
        logger.warning("[NIJA] LIVE_TRADING=1 but Coinbase keys missing or invalid — running in Dummy mode ⚠️")
    else:
        logger.info("[NIJA] Running in safe Dummy mode (LIVE_TRADING=0)")

# -------------------------------
# Log final status
# -------------------------------
logger.info(f"[NIJA] Module loaded. DRY_RUN={DRY_RUN} LIVE_TRADING={LIVE_TRADING} client_is_dummy={client_is_dummy}")
