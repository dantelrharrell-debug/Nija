# nija_render_worker.py
import os, logging, time
from time import sleep

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

try:
    from coinbase_advanced.client import Client
except Exception as e:
    logger.exception("coinbase_advanced import failed (will exit).")
    raise SystemExit("coinbase_advanced import failed")

COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
COINBASE_ACCOUNT_ID = os.getenv("COINBASE_ACCOUNT_ID")

missing = [k for k,v in {
    "COINBASE_API_KEY": COINBASE_API_KEY,
    "COINBASE_API_SECRET": COINBASE_API_SECRET,
    "COINBASE_API_PASSPHRASE": COINBASE_API_PASSPHRASE,
    "COINBASE_ACCOUNT_ID": COINBASE_ACCOUNT_ID
}.items() if not v]

if missing:
    logger.error(f"Missing Coinbase env vars: {missing}. Exiting.")
    raise SystemExit(f"Missing Coinbase env vars: {missing}")

try:
    client = Client(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET, api_passphrase=COINBASE_API_PASSPHRASE)
    logger.info("✅ Coinbase client created")
except Exception as e:
    logger.exception("Failed to create Coinbase client")
    raise SystemExit("Failed to create Coinbase client")

def test_connection():
    try:
        accounts = client.get_accounts()
        logger.info(f"✅ Accounts fetched: {len(accounts)}")
        funded = next((a for a in accounts if a.get("id") == COINBASE_ACCOUNT_ID), None)
        if funded:
            logger.info(f"✅ Funded account found: {funded['id']} balance={funded['balance']}")
            return True
        else:
            logger.error("❌ Funded account not found in accounts list")
            return False
    except Exception as e:
        logger.exception("Coinbase connection test failed")
        return False

def trading_loop():
    logger.info("⚡ Trading loop starting (placeholder).")
    while True:
        try:
            accounts = client.get_accounts()
            logger.info(f"Tick: fetched {len(accounts)} accounts")
            time.sleep(10)
        except Exception as e:
            logger.exception("Error in trading loop; sleeping 5s")
            time.sleep(5)

if __name__ == "__main__":
    ok = test_connection()
    if not ok:
        logger.error("Cannot start trading: connection test failed")
        raise SystemExit("Coinbase connection test failed")
    trading_loop()
