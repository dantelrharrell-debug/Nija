# start_nija_live_hmac.py
import logging
import asyncio
from loguru import logger
from nija_hmac_client import CoinbaseClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija.bot.hmac")

async def fetch_hmac_accounts(client):
    # prefer explicit v3 brokerage accounts path for Advanced
    preferred_paths = [
        "/api/v3/brokerage/accounts",   # Advanced production path
        "/v3/accounts",                 # older/variant (we rewrite in client)
        "/v2/accounts",                 # legacy retail path if needed
        "/accounts"
    ]
    for p in preferred_paths:
        status, data = client.request(method="GET", path=p)
        if status == 200:
            # ensure we return a list of accounts
            if isinstance(data, dict) and data.get("data"):
                return status, data
            # some endpoints may return list directly
            if isinstance(data, list):
                return status, {"data": data}
        else:
            logger.warning("⚠️ %s not found (status %s), trying next...", p, status)
    return None, None

async def main_loop():
    client = CoinbaseClient()
    logger.info("Starting HMAC live bot...")
    status, accounts = await asyncio.to_thread(lambda: fetch_hmac_accounts_sync(client))
    if not status:
        logger.error("No HMAC accounts found. Aborting bot.")
        return
    logger.info("Accounts fetched successfully: %s accounts", len(accounts.get("data", [])))
    # Placeholder: start your trading loop here
    logger.info("✅ Ready to start trading (bot loop not implemented in this starter script).")

def fetch_hmac_accounts_sync(client):
    # synchronous wrapper for the client.request (client.request is sync)
    status, accounts = None, None
    try:
        status, accounts = client.request(method="GET", path="/api/v3/brokerage/accounts")
        if status == 200:
            return status, accounts
        logger.warning("v3 didn't work; trying retail v2...")
        status, accounts = client.request(method="GET", path="/v2/accounts")
        if status == 200:
            return status, accounts
        logger.warning("Retail v2 didn't work; trying /accounts...")
        status, accounts = client.request(method="GET", path="/accounts")
        if status == 200:
            return status, accounts
    except Exception as e:
        logger.exception("Exception while fetching accounts: %s", e)
    return None, None

if __name__ == "__main__":
    asyncio.run(main_loop())
    
