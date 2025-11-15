import os
import sys
import time
from loguru import logger
from app.nija_client import CoinbaseClient

# -----------------------------
# Logger Setup
# -----------------------------
logger.remove()
logger.add(sys.stdout, level="INFO", enqueue=True)
logger.info("Nija bot starting... (main.py)")

# -----------------------------
# Initialize Coinbase Client
# -----------------------------
try:
    client = CoinbaseClient(
        api_key=os.environ["COINBASE_API_KEY"],
        org_id=os.environ["COINBASE_ORG_ID"],
        pem=os.environ["COINBASE_PEM_CONTENT"]
    )
    logger.info("CoinbaseClient initialized")
except Exception as e:
    logger.exception("Failed to initialize CoinbaseClient: {}", e)
    sys.exit(1)
