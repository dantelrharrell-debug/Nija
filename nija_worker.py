# nija_render_worker.py
import os
import logging
from time import sleep

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

try:
    from coinbase_advanced.client import Client
except Exception as e:
    logger.exception("coinbase_advanced import failed")
    raise

COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
COINBASE_ACCOUNT_ID = os.getenv("COINBASE_ACCOUNT_ID")

if not all([COINBASE_API_KEY, COINBASE_API_SECRET, COINBASE_API_PASSPHRASE, COINBASE_ACCOUNT_ID]):
    logger.error("Missing Coinbase env vars. Cannot start worker.")
    raise SystemExit("Missing Coinbase env vars")

client = Client(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET, api_passphrase=COINBASE_API_PASSPHRASE)

def test_connection():
    try:
        accounts = client.get_accounts()
        logger.info("✅ Coinbase API reachable. Accounts fetched.")
        for a in accounts:
            logger.info(f"acct: {a.get('id')} {a.get('currency')} balance={a.get('balance')}")
        funded = next((a for a in accounts if a.get('id') == COINBASE_ACCOUNT_ID), None)
        if funded:
            logger.info(f"✅ Funded account found: {funded['id']} balance: {funded['balance']}")
            return True
        else:
            logger.error("❌ Funded account ID not found in accounts")
            return False
    except Exception as e:
        logger.exception("Coinbase connection test failed")
        return False

def trading_loop():
    logger.info("⚡ Trading loop started (placeholder).")
    while True:
        try:
            # Replace with your real trading logic
            logger.info("Tick - would evaluate signals and place trades here.")
            sleep(10)
        except Exception as e:
            logger.exception("Error in trading loop, sleeping 5s")
            sleep(5)

if __name__ == "__main__":
    if test_connection():
        trading_loop()
    else:
        logger.error("Cannot start trading. Fix Coinbase connection.")
        raise SystemExit("Coinbase connection test failed")
