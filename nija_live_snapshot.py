#!/usr/bin/env python3
import os
import sys
import logging
from nija_client import get_client, check_live_status

# --- Logging setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_live_snapshot")

# --- Environment Variables ---
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_PEM_PATH = os.environ.get("COINBASE_PEM_PATH")
SANDBOX = os.environ.get("SANDBOX", "0") == "1"

if not COINBASE_API_KEY:
    logger.error("COINBASE_API_KEY not set. Exiting.")
    sys.exit(1)

if not COINBASE_PEM_PATH or not os.path.exists(COINBASE_PEM_PATH):
    logger.error(f"COINBASE_PEM_PATH is missing or invalid: {COINBASE_PEM_PATH}")
    sys.exit(1)

# --- Initialize Coinbase Client ---
try:
    client = get_client(
        api_key=COINBASE_API_KEY,
        pem_path=COINBASE_PEM_PATH,
        sandbox=SANDBOX
    )
    logger.info("✅ CoinbaseClient initialized successfully")
except Exception as e:
    logger.exception("❌ Failed to initialize CoinbaseClient, exiting.")
    sys.exit(1)

# --- Startup Live Check ---
logger.info("=== NIJA STARTUP LIVE CHECK ===")
live_status = check_live_status(client)
if live_status:
    logger.info("✅ NIJA is live and ready for trading")
else:
    logger.warning("⚠️ NIJA is NOT live — check API keys and connectivity")

# --- Example Snapshot: Fetch Accounts ---
try:
    accounts = client.get_accounts()
    logger.info(f"Retrieved {len(accounts)} accounts from Coinbase")
except Exception as e:
    logger.exception("Failed to fetch accounts from Coinbase")

# --- Placeholder for trading loop ---
logger.info("NIJA Live Snapshot setup complete. Trading loop goes here.")
