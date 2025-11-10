# start_bot.py (root)
import sys
from loguru import logger
logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

try:
    from nija_client import CoinbaseClient
except Exception as e:
    logger.error(f"Cannot import CoinbaseClient from root nija_client: {e}")
    sys.exit(1)

def main():
    logger.info("Starting Nija loader (robust).")

    try:
        client = CoinbaseClient(advanced=True)
        accounts = []
        if hasattr(client, "fetch_advanced_accounts"):
            accounts = client.fetch_advanced_accounts()
        else:
            # attempt a generic request path if needed
            try:
                status, data = client.request("GET", "/v3/accounts")
                if status == 200 and data:
                    accounts = data.get("data", []) if isinstance(data, dict) else []
            except Exception:
                accounts = []

        if not accounts:
            logger.error("No accounts returned. Verify COINBASE env vars, key permissions, and COINBASE_BASE.")
            sys.exit(1)

        logger.info("Accounts:")
        for a in accounts:
            logger.info(f" - {a.get('name', a.get('id', '<unknown>'))}")
        logger.info("✅ HMAC/Advanced account check passed. Ready to start trading loop (not included here).")

    except Exception as e:
        logger.exception(f"Error during client init / account check: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
