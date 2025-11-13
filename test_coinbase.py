# test_coinbase.py
import os
from app.nija_client import CoinbaseClient
from loguru import logger

logger.add(lambda msg: print(msg, end=""), level="INFO")

# Make sure these env vars are set in your terminal/session:
# COINBASE_API_KEY_ID, COINBASE_PEM, COINBASE_ORG_ID
# For Railway, you can set them in the environment variables panel.

try:
    client = CoinbaseClient()
    accounts = client.get_accounts()
    logger.info("Accounts fetched successfully: {}", accounts)
except Exception as e:
    logger.exception("Failed to fetch accounts: {}", e)
