# bot.py
import os
import sys
import time
import logging
from loguru import logger

# Configure both standard logging and loguru so messages are visible in Railway logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger.remove()
logger.add(sys.stdout, level="INFO", backtrace=False, diagnose=False)

# Required environment variables
REQUIRED = [
    "GITHUB_PAT",
    "COINBASE_API_KEY",
    "COINBASE_API_SECRET",
    "COINBASE_ACCOUNT_ID",
]

missing = [name for name in REQUIRED if not os.environ.get(name)]
if missing:
    logger.error(f"❌ Missing required environment variables: {missing}")
    sys.exit(1)

# Import Coinbase Advanced AFTER runtime installation (start_bot.sh installs it)
try:
    from coinbase_advanced.client import Client
except Exception as e:
    logger.exception("❌ coinbase_advanced import failed. Ensure start_bot.sh installed it at runtime.")
    raise

# Load Coinbase creds
API_KEY = os.environ.get("COINBASE_API_KEY")
API_SECRET = os.environ.get("COINBASE_API_SECRET")
API_PASSPHRASE = os.environ.get("COINBASE_API_PASSPHRASE")  # optional
COINBASE_ACCOUNT_ID = os.environ.get("COINBASE_ACCOUNT_ID")
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")  # optional
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")  # optional (for PEM auth)

def init_client():
    try:
        # Adjust parameters for your version of the SDK if needed (org_id/pem handling)
        client = Client(
            api_key=API_KEY,
            api_secret=API_SECRET,
            api_passphrase=API_PASSPHRASE
        )
        logger.info("✅ Coinbase client object created")
        return client
    except Exception as e:
        logger.exception("❌ Failed to initialize Coinbase client")
        raise

def test_connection(client):
    try:
        accounts = client.get_accounts()
        logger.info(f"✅ Accounts fetched: {len(accounts)}")
        funded = next((a for a in accounts if a.get("id") == COINBASE_ACCOUNT_ID), None)
        if funded:
            bal = funded.get("balance", {}).get("amount") if funded.get("balance") else "unknown"
            currency = funded.get("currency", "unknown")
            logger.info(f"✅ Funded account found: id={COINBASE_ACCOUNT_ID} currency={currency} balance={bal}")
            return True
        else:
            logger.error("❌ Funded account ID not found among fetched accounts")
            # Log some sample account ids for debugging
            sample_ids = [a.get("id") for a in accounts][:10]
            logger.info(f"Sample account IDs: {sample_ids}")
            return False
    except Exception as e:
        logger.exception("❌ Error while testing Coinbase connection")
        return False

def run_bot_loop(client):
    logger.info("⚡ Entering main bot loop (placeholder). Will log balances every 30s.")
    while True:
        try:
            accounts = client.get_accounts()
            # print a small summary
            for a in accounts[:10]:
                logger.info(f"Account: id={a.get('id')} currency={a.get('currency')} balance={a.get('balance')}")
            # PLACE TRADING LOGIC HERE (disabled until confirmed)
            time.sleep(30)
        except Exception as e:
            logger.exception("❌ Exception in main loop, sleeping for 10s then retrying")
            time.sleep(10)

if __name__ == "__main__":
    client = init_client()
    ok = test_connection(client)
    if not ok:
        logger.error("Cannot proceed until connection works. Check keys, permissions, and IP whitelist.")
        sys.exit(1)
    # All good — start loop
    run_bot_loop(client)
