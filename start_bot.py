# start_bot.py (root)
import os
import sys
from loguru import logger
logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

try:
    from nija_client import CoinbaseClient
except Exception as e:
    logger.error(f"Cannot import CoinbaseClient from root nija_client: {e}")
    sys.exit(1)


def fix_pem_env_var():
    """Convert literal '\\n' in PEM env var to real newlines"""
    pem = os.getenv("COINBASE_PEM_CONTENT")
    if pem and "\\n" in pem:
        os.environ["COINBASE_PEM_CONTENT"] = pem.replace("\\n", "\n")
        logger.info("✅ Fixed PEM env var formatting.")


def main():
    logger.info("Starting Nija loader (robust).")

    # Fix PEM formatting if needed
    fix_pem_env_var()

    try:
        client = CoinbaseClient(advanced=True, debug=True)
    except ValueError as ve:
        logger.error(f"Error during client init: {ve}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Unexpected error during CoinbaseClient init: {e}")
        sys.exit(1)

    try:
        accounts = client.fetch_advanced_accounts()
        if not accounts:
            logger.error("No accounts returned. Verify COINBASE env vars, key permissions, and COINBASE_ADVANCED_BASE.")
            sys.exit(1)

        logger.info("Accounts fetched successfully:")
        for a in accounts:
            logger.info(f" - {a.get('name', a.get('id', '<unknown>'))}")

        logger.info("✅ Coinbase connection verified. Bot ready.")
    except Exception as e:
        logger.exception(f"Error fetching accounts: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
