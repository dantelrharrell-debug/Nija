# test_coinbase_connection.py
import os
from loguru import logger
from nija_client import CoinbaseClient

logger.add(lambda msg: print(msg, end=""))  # log to stdout

def main():
    try:
        client = CoinbaseClient()
    except Exception as e:
        logger.error("Failed to initialize CoinbaseClient: {}", e)
        raise SystemExit(1)

    try:
        accts = client.list_accounts()
        # attempt to get simple length without printing account contents
        try:
            count = len(accts)
        except Exception:
            # if object isn't list-like, coerce to list length safely
            try:
                count = len(list(accts))
            except Exception:
                count = "unknown"
        logger.info("Connection OK — accounts_count={}", count)
        return 0
    except Exception as e:
        logger.error("Failed account fetch: {}", e)
        raise SystemExit(2)

if __name__ == "__main__":
    main()
