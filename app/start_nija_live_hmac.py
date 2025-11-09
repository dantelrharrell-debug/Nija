# start_nija_live_advanced.py
import os
import asyncio
from nija_client import CoinbaseClient
from loguru import logger

# --- Initialize client ---
client = CoinbaseClient(
    api_key=os.getenv("COINBASE_API_KEY"),
    api_secret=os.getenv("COINBASE_API_SECRET"),
    private_key_path=os.getenv("COINBASE_PRIVATE_KEY_PATH"),
    org_id=os.getenv("COINBASE_ORG_ID"),
    base=os.getenv("COINBASE_BASE", "https://api.cdp.coinbase.com"),
    advanced=True
)

# --- Fetch accounts ---
def fetch_advanced_accounts():
    try:
        accounts = client.get_accounts()
        if not accounts:
            logger.error("❌ No Advanced accounts found. Check your keys and org ID.")
            return []
        return accounts
    except Exception as e:
        logger.exception(f"Failed to fetch accounts: {e}")
        return []

# --- Main loop ---
async def main_loop():
    logger.info("Starting Advanced live bot...")
    accounts = fetch_advanced_accounts()
    if not accounts:
        logger.error("No accounts returned. Bot will not start.")
        return
    logger.info(f"Fetched {len(accounts)} accounts. Bot is ready.")
    # TODO: Insert your trading logic here
    while True:
        await asyncio.sleep(5)  # placeholder for live operations

if __name__ == "__main__":
    asyncio.run(main_loop())
