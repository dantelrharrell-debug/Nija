#!/usr/bin/env python3
import os
import time
import logging
from backoff import expo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

REQUIRED = ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_ACCOUNT_ID"]

missing = [k for k in REQUIRED if not os.getenv(k)]
if missing:
    logging.error(f"Missing required environment variables: {missing}. Worker cannot start.")
    raise SystemExit(1)

GITHUB_PAT = os.getenv("GITHUB_PAT")
if not GITHUB_PAT:
    logging.error("Missing GITHUB_PAT; coinbase-advanced cannot be installed at runtime.")
    raise SystemExit(1)

# Import client (the package should be installed by start_all.sh)
try:
    from coinbase_advanced.client import Client
except Exception as e:
    logging.exception("coinbase_advanced import failed. Is the package installed?")
    raise

COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_ACCOUNT_ID = os.getenv("COINBASE_ACCOUNT_ID")

def init_client():
    try:
        client = Client(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET)
        logging.info("✅ Coinbase client object created")
        return client
    except Exception as e:
        logging.exception("Failed to construct Coinbase client")
        raise

@expo(max_time=60, max_tries=10)  # exponential backoff for initial connection
def wait_for_connection(client):
    logging.info("Checking Coinbase accounts...")
    accounts = client.get_accounts()
    if not accounts:
        raise RuntimeError("No accounts returned")
    # find funded account if provided
    funded = next((a for a in accounts if a.get("id") == COINBASE_ACCOUNT_ID), None)
    if funded:
        logging.info(f"✅ Connected to funded account: {funded.get('currency')} balance={funded.get('balance')}")
    else:
        logging.warning("Funded account ID not found among accounts returned. Continuing but double-check COINBASE_ACCOUNT_ID.")
    return True

def trading_loop(client):
    logging.info("Entering trading loop (placeholder) — will log account balances every 30s")
    while True:
        try:
            accounts = client.get_accounts()
            for a in accounts:
                bal = a.get("balance", {})
                logging.info(f"Account {a.get('id')} currency={a.get('currency')} balance={bal.get('amount')}")
            # TODO: replace with your actual trading logic
            time.sleep(30)
        except Exception as e:
            logging.exception("Error in trading loop — will sleep and retry")
            time.sleep(5)

def main():
    client = init_client()
    wait_for_connection(client)
    trading_loop(client)

if __name__ == "__main__":
    main()
