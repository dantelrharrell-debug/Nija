# nija_client.py
import os
import logging
from decimal import Decimal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# Path to PEM file
PEM_PATH = "/opt/render/project/secrets/coinbase.pem"

# Attempt to import CoinbaseClient
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] Successfully imported CoinbaseClient")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not available. Using DummyClient instead.")
    CoinbaseClient = None
except Exception as e:
    logger.error(f"[NIJA] Error importing CoinbaseClient: {e}")
    CoinbaseClient = None


def write_pem_file(content: str):
    """Write PEM file if missing or corrupted."""
    try:
        with open(PEM_PATH, "w") as f:
            f.write(content)
        logger.info(f"[NIJA] PEM file written to {PEM_PATH}")
    except Exception as e:
        logger.error(f"[NIJA] Failed to write PEM file: {e}")


def init_client():
    """Initialize Coinbase RESTClient with PEM and API credentials."""
    if CoinbaseClient is None:
        logger.warning("[NIJA] CoinbaseClient unavailable, returning None")
        return None

    # Ensure PEM exists
    pem_content = os.getenv("COINBASE_PEM_CONTENT")
    if pem_content:
        if not os.path.exists(PEM_PATH):
            write_pem_file(pem_content)

    try:
        client = CoinbaseClient(
            key=os.getenv("COINBASE_API_KEY"),
            secret=os.getenv("COINBASE_API_SECRET"),
            passphrase=os.getenv("COINBASE_API_PASSPHRASE"),
            pem_path=PEM_PATH
        )
        logger.info("[NIJA] Coinbase RESTClient initialized successfully")
        return client
    except Exception as e:
        logger.error(f"[NIJA] Failed to initialize Coinbase client: {e}")
        return None
