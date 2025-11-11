import sys
from loguru import logger
from nija_client import CoinbaseClient

def main():
    logger.info("Starting Nija loader (robust)...")

    try:
        client = CoinbaseClient(
            jwt_iss="YOUR_JWT_ISS_HERE",
            jwt_pem="""-----BEGIN EC PRIVATE KEY-----
YOUR_JWT_PEM_HERE
-----END EC PRIVATE KEY-----"""
        )
        logger.info("CoinbaseClient initialized successfully (Advanced/JWT).")

        accounts = client.get_accounts()
        if not accounts:
            logger.error("❌ Connection test failed! /accounts returned no data.")
            sys.exit(1)

        logger.info("✅ Connection test succeeded!")
        logger.debug(f"Accounts (truncated): {repr(accounts)[:300]}")
        logger.info("Nija loader ready to trade...")

    except Exception:
        logger.exception("❌ Failed to initialize CoinbaseClient or connect.")
        sys.exit(1)

if __name__ == "__main__":
    main()
