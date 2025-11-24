# scripts/test_coinbase.py
import os
import json
import logging
from nija_client import CoinbaseClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_coinbase")

def main():
    logger.info("Starting Coinbase test script")

    # Print which env vars are present (mask secrets)
    def present(name):
        v = os.environ.get(name)
        if not v:
            return "(missing)"
        if "KEY" in name or "SECRET" in name or "PEM" in name or "JWT" in name:
            return "SET"
        return v

    env_vars = ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_ORG_ID",
                "COINBASE_API_PASSPHRASE", "COINBASE_PRIVATE_KEY_PATH",
                "COINBASE_PEM_CONTENT", "COINBASE_JWT", "COINBASE_BASE_URL"]
    logger.info("Env summary: " + ", ".join(f"{n}={present(n)}" for n in env_vars))

    # Initialize client
    try:
        client = CoinbaseClient()
    except Exception as e:
        logger.exception("Failed to instantiate CoinbaseClient")
        return

    # Fetch accounts
    try:
        accounts = client.fetch_accounts()
        logger.info(f"fetch_accounts returned {len(accounts)} items")
        try:
            print(json.dumps(accounts, indent=2))
        except Exception:
            logger.info("accounts (non-json) -> printed repr")
            print(repr(accounts))
    except Exception as e:
        logger.exception("fetch_accounts raised an exception")

    # Fetch open orders
    try:
        orders = client.fetch_open_orders()
        logger.info(f"fetch_open_orders returned {len(orders)} items")
    except Exception as e:
        logger.exception("fetch_open_orders raised an exception")

    # Fetch fills (no product specified)
    try:
        fills = client.fetch_fills()
        logger.info(f"fetch_fills returned {len(fills)} items")
    except Exception as e:
        logger.exception("fetch_fills raised an exception")

    # Do NOT place real orders in this smoke test (unless you intentionally want to)
    logger.info("Test complete. KEEP LIVE_TRADING=0 until you confirm everything is correct.")

if __name__ == "__main__":
    main()
