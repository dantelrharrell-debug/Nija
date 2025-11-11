# start_bot.py
import os
import sys
from loguru import logger
from nija_client import CoinbaseClient

def main():
    logger.info("Starting Nija loader (robust)...")

    # Detect mode automatically
    use_jwt = all([
        os.getenv("COINBASE_ISS"),
        os.getenv("COINBASE_PEM_CONTENT"),
        os.getenv("COINBASE_ADVANCED_BASE")
    ])

    try:
        if use_jwt:
            logger.info("Detected Coinbase Advanced (JWT) mode.")
            client = CoinbaseClient(
                iss=os.getenv("COINBASE_ISS"),
                pem=os.getenv("COINBASE_PEM_CONTENT"),
                base_url=os.getenv("COINBASE_ADVANCED_BASE")
            )
        else:
            logger.info("Using standard HMAC Coinbase API mode.")
            client = CoinbaseClient(
                api_key=os.getenv("COINBASE_API_KEY"),
                api_secret=os.getenv("COINBASE_API_SECRET"),
                passphrase=os.getenv("COINBASE_API_PASSPHRASE"),
                base_url=os.getenv("COINBASE_API_BASE")
            )

        # Test connection
        logger.info("Testing Coinbase connection...")
        status, resp = client.test_connection()
        if status != "ok" or not resp:
            logger.error("❌ Connection test failed! Check API keys and endpoint.")
            sys.exit(1)

        logger.info("✅ Connection test succeeded!")
        logger.debug(f"Response: {repr(resp)[:300]}")  # truncate output

        # Continue with main bot logic here
        # client.run() or loader.start(), etc.
        logger.info("Nija loader ready to trade...")

    except Exception as e:
        logger.exception("❌ Failed to initialize CoinbaseClient or connect.")
        sys.exit(1)

if __name__ == "__main__":
    main()
