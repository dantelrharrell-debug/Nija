#!/usr/bin/env python3
import os
import tempfile
import logging
from nija_coinbase_jwt_client import CoinbaseJWTClient

# ---------------------------
# Logging setup
# ---------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.bot.jwt")

# ---------------------------
# PEM Handling (from .env)
# ---------------------------
pem_content = os.getenv("COINBASE_PEM_CONTENT")
if not pem_content:
    raise ValueError("COINBASE_PEM_CONTENT not set in .env")

# Create a temporary PEM file (required by JWT client)
temp_pem = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
temp_pem.write(pem_content.encode())
temp_pem.flush()
os.environ["COINBASE_PRIVATE_KEY_PATH"] = temp_pem.name

# ---------------------------
# Initialize JWT Client
# ---------------------------
client = CoinbaseJWTClient()

# ---------------------------
# Fetch and print accounts
# ---------------------------
try:
    accounts = client.list_accounts()
    logger.info("Accounts fetched successfully:")
    for acct in accounts:
        logger.info(acct)
except Exception as e:
    logger.error("Failed to fetch accounts: %s", e)
    raise e

# ---------------------------
# Placeholder: Trading loop
# ---------------------------
logger.info("Trading loop placeholder — add your signals, sizing, and execution logic here.")
# Example structure:
# while True:
#     # 1) Fetch prices / indicators (VWAP, RSI)
#     # 2) Determine trade size (2%-10% of account equity)
#     # 3) Execute orders via client.request(...)
#     # 4) Sleep or await next signal
#     pass

# ---------------------------
# Note for next upgrade
# ---------------------------
logger.info("Next step: integrate dynamic trade sizing, VWAP/RSI indicators, and multi-pair concurrency for aggressive crypto bot setup.")
