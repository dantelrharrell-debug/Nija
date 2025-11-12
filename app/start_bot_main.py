from app.nija_client import CoinbaseClient
from loguru import logger
import os

def main():
    logger.info("Starting Nija loader (robust)...")

    # Coinbase client
    client = CoinbaseClient(
        base_url=os.getenv("COINBASE_BASE", "https://api.coinbase.com/v2"),
        auth_mode=os.getenv("COINBASE_AUTH_MODE", "advanced"),  # must exist in Railway
        api_key=os.getenv("COINBASE_API_KEY"),
        key_id=os.getenv("COINBASE_KEY_ID"),
        jwt_iss=os.getenv("COINBASE_JWT_ISS"),
        pem_content=os.getenv("COINBASE_JWT_PEM"),
        org_id=os.getenv("COINBASE_ORG_ID"),
    )

    logger.info("CoinbaseClient initialized. base=%s", client.base_url)

    # Test connection
    accounts = client.get_accounts()
    if not accounts:
        logger.error("❌ Connection test failed! /accounts returned no data.")
        return

    logger.info("✅ Connection test succeeded! Accounts: %s", accounts)
