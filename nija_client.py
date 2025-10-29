# nija_client.py
import os
import logging

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Load environment variables ---
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_PEM_PATH = os.environ.get("COINBASE_PEM_PATH", "/opt/render/project/secrets/coinbase.pem")
SANDBOX = os.environ.get("SANDBOX", None)

# --- Try importing CoinbaseClient ---
CoinbaseClient = None
try:
    from coinbase_advanced_py import CoinbaseClient
    logger.info("[NIJA] Successfully imported CoinbaseClient")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not available. Using DummyClient")

# --- DummyClient fallback ---
class DummyClient:
    def __init__(self, *args, **kwargs):
        logger.warning("[NIJA] DummyClient initialized - live trading disabled")

    def get_accounts(self):
        return []

    def place_order(self, *args, **kwargs):
        logger.warning("[NIJA] DummyClient: place_order called")

# --- Initialize client ---
if CoinbaseClient:
    try:
        client = CoinbaseClient(
            api_key=COINBASE_API_KEY,
            pem_file_path=COINBASE_PEM_PATH,
            sandbox=SANDBOX is not None  # Use sandbox if SANDBOX is set
        )
        logger.info("[NIJA] CoinbaseClient initialized - ready for live trading")
    except Exception as e:
        logger.error(f"[NIJA] Failed to initialize CoinbaseClient: {e}")
        client = DummyClient()
else:
    client = DummyClient()

# --- Live check helper ---
def check_live_status():
    try:
        accounts = client.get_accounts()
        live = accounts is not None
    except Exception:
        live = False
    return live
