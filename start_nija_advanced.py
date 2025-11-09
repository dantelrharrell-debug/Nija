import asyncio
from loguru import logger
from nija_hmac_client import CoinbaseClient

# Initialize Advanced client
client = CoinbaseClient(advanced=True)

async def fetch_advanced_accounts():
    try:
        status, data = client.request("GET", "/v3/accounts")
        if status != 200 or not data:
            logger.error(f"❌ Failed to fetch accounts. Status: {status}")
            return []
        logger.info(f"✅ Fetched {len(data.get('data', []))} accounts.")
        return data.get("data", [])
    except Exception as e:
        logger.exception(f"Failed to fetch accounts: {e}")
        return []

async def main_loop():
    logger.info("Starting HMAC Advanced bot...")
    accounts = await fetch_advanced_accounts()
    if not accounts:
        logger.error("No accounts returned. Bot will not start.")
        return
    # Start your trading loop here
    logger.info("✅ Accounts loaded, bot running...")
    while True:
        await asyncio.sleep(5)  # placeholder for your bot loop

if __name__ == "__main__":
    asyncio.run(main_loop())
