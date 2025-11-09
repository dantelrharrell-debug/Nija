import asyncio
from loguru import logger
from nija_hmac_client import fetch_hmac_accounts

async def main_loop():
    logger.info("Starting HMAC live bot...")
    accounts = fetch_hmac_accounts()
    if not accounts:
        logger.error("No HMAC accounts found. Aborting bot.")
        return

    logger.info(f"Accounts fetched: {accounts}")

    # Example live loop (replace with your trading logic)
    while True:
        for account in accounts:
            # Put trading logic here
            logger.info(f"Checking account: {account['id']}")
        await asyncio.sleep(10)  # Loop delay

if __name__ == "__main__":
    asyncio.run(main_loop())
