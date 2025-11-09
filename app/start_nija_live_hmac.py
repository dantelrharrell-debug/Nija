#!/usr/bin/env python3
# start_nija_live_hmac.py
import logging
from loguru import logger
from nija_hmac_client import CoinbaseClient

logger = logging.getLogger("nija.bot.hmac")
logging.basicConfig(level=logging.INFO)

def fetch_hmac_accounts():
    client = CoinbaseClient()
    # Try the canonical advanced v3 brokerage accounts path first (client handles attempts)
    status, accounts = client.request(method="GET", path="/api/v3/brokerage/accounts")
    if status == 200:
        logger.info("✅ Advanced accounts fetched (v3).")
        return accounts.get("data", []) if isinstance(accounts, dict) else accounts
    # if advanced returned non-200, try retail endpoints explicitly
    logger.warning(f"Attempt v3 status={status}; trying retail /v2/accounts fallback.")
    status2, accounts2 = client.request(method="GET", path="/v2/accounts")
    if status2 == 200:
        return accounts2.get("data", []) if isinstance(accounts2, dict) else accounts2
    # Nothing worked
    logger.error(f"❌ Failed to fetch accounts. Status: {status2} resp: {accounts2}")
    return []

if __name__ == "__main__":
    accounts = fetch_hmac_accounts()
    if not accounts:
        logger.error("No HMAC accounts found. Aborting bot.")
    else:
        logger.info("Accounts:")
        for a in accounts:
            # defensive printing
            if isinstance(a, dict):
                name = a.get("name") or a.get("currency") or a.get("id")
                bal = a.get("balance", {}).get("amount") if isinstance(a.get("balance"), dict) else a.get("balance")
                logger.info(f" - {name}: {bal}")
            else:
                logger.info(f" - {a}")
