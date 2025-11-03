import os
import logging
from coinbase_advanced_py import RESTClient
from cryptography.hazmat.primitives import serialization

logger = logging.getLogger("nija_client")
logging.basicConfig(level=logging.INFO)

# -------------------------------
# Load PEM key from env var
# -------------------------------
pem_env = os.getenv("COINBASE_PEM_KEY")
if not pem_env:
    logger.error("COINBASE_PEM_KEY environment variable not set")
    raise ValueError("COINBASE_PEM_KEY not set")

# Convert literal \n to actual line breaks
pem_bytes = pem_env.replace("\\n", "\n").encode()

# Load private key
try:
    private_key = serialization.load_pem_private_key(
        pem_bytes,
        password=None,
    )
    logger.info("[NIJA] PEM key loaded successfully ✅")
except Exception as e:
    logger.error(f"[NIJA] Failed to load PEM key: {e}")
    raise

# -------------------------------
# Initialize RESTClient
# -------------------------------
try:
    client = RESTClient(
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET"),
        pem_key=private_key,
    )
    logger.info("[NIJA] RESTClient initialized successfully ✅")
except Exception as e:
    logger.error(f"[NIJA] Failed to initialize RESTClient: {e}")
    raise

# -------------------------------
# Test fetching USD balance
# -------------------------------
try:
    usd_balance = client.get_account_balance("USD")
    logger.info(f"[NIJA] USD balance fetched: {usd_balance}")
except Exception as e:
    logger.error(f"[NIJA] Failed to fetch USD balance: {e}")
