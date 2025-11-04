import os
import base64
import sys

# ------------------------------
# Coinbase API preflight check
# ------------------------------

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # can be None

if not API_KEY or not API_SECRET:
    print("❌ Coinbase API_KEY or API_SECRET is missing!")
    sys.exit(1)

# Check secret length
try:
    decoded_secret = base64.b64decode(API_SECRET)
except Exception as e:
    print(f"❌ Failed to decode API_SECRET: {e}")
    sys.exit(1)

if len(decoded_secret) != 32:
    print(f"❌ API_SECRET is {len(decoded_secret)} bytes after base64 decode, but must be exactly 32 bytes.")
    sys.exit(1)

print("✅ Coinbase API credentials look valid (preflight check passed)")

#!/usr/bin/env python3
"""
NIJA Debug Script: Verify Coinbase Advanced API credentials and USD Spot balance
"""

import os
import logging
from nija_client import get_usd_spot_balance, get_all_accounts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_debug")

# ----------------------------
# Print environment variables (masked)
# ----------------------------
def mask(val):
    if not val:
        return None
    return val[:4] + "****"

logger.info("COINBASE_API_KEY: %s", mask(os.getenv("COINBASE_API_KEY")))
logger.info("COINBASE_API_SECRET: %s", mask(os.getenv("COINBASE_API_SECRET")))
logger.info("COINBASE_API_PASSPHRASE: %s", mask(os.getenv("COINBASE_API_PASSPHRASE")))

# ----------------------------
# Test USD Spot Balance
# ----------------------------
try:
    usd_balance = get_usd_spot_balance()
    logger.info("✅ USD Spot Balance: %s", usd_balance)
except Exception as e:
    logger.exception("❌ Failed to fetch USD Spot balance: %s", e)

# ----------------------------
# Test fetching all accounts
# ----------------------------
try:
    accounts = get_all_accounts()
    logger.info("✅ Fetched %d accounts", len(accounts))
    for acct in accounts:
        logger.info("Account: %s | Currency: %s | Balance: %s", 
                    acct.get("name"), 
                    acct.get("balance", {}).get("currency"), 
                    acct.get("balance", {}).get("amount"))
except Exception as e:
    logger.exception("❌ Failed to fetch all accounts: %s", e)
