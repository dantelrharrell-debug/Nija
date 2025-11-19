# nija_worker.py
import logging
import time
from nija_client import get_coinbase_client, COINBASE_ACCOUNT_ID

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

def test_connection():
    try:
        client = get_coinbase_client()
        accounts = client.get_accounts()
        logger.info(f"✅ Coinbase connection verified. {len(accounts)} accounts found.")
        if COINBASE_ACCOUNT_ID:
            funded = next((a for a in accounts if a.get("id") == COINBASE_ACCOUNT_ID), None)
            if funded:
                logger.info(f"✅ Funded account found: {funded['currency']} balance {funded['balance']['amount']}")
            else:
                logger.warning("⚠️ Funded account ID not found among accounts.")
        return client
    except Exception as e:
        logger.exception("❌ Coinbase connection test failed")
        raise

def run_trading_loop(client):
    logger.info("⚡ Trading loop starting (placeholder)...")
    while True:
        try:
            # Example: list balances every 30s — replace with your real trading logic
            accounts = client.get_accounts()
            for a in accounts:
                logger.info(f"Account {a.get('currency')} -> balance {a.get('balance', {}).get('amount')}")
            time.sleep(30)
        except Exception as e:
            logger.exception("Error in trading loop, sleeping 10s then retrying")
            time.sleep(10)

if __name__ == "__main__":
    client = test_connection()
    run_trading_loop(client)
