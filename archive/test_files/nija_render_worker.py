# nija_render_worker.py
import os
from time import sleep
from loguru import logger

logger.add("/tmp/worker.log", rotation="10 MB", retention="7 days", level="INFO")

def dump_env():
    keys = ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_API_PASSPHRASE",
            "COINBASE_PEM_CONTENT", "COINBASE_ORG_ID", "COINBASE_ACCOUNT_ID", "LIVE_TRADING"]
    logger.info("ENV snapshot:")
    for k in keys:
        v = os.getenv(k)
        logger.info(f"  {k}: {'MISSING' if not v else 'present'}")

def main():
    from nija_client import CoinbaseClient
    dump_env()
    try:
        client = CoinbaseClient()
    except Exception:
        logger.exception("Failed to initialize Coinbase client — worker exiting")
        raise SystemExit("Coinbase init failed")

    # quick test
    try:
        accts = client.list_accounts()
        logger.info(f"Initial account fetch succeeded: count={len(accts) if accts is not None else 'unknown'}")
    except Exception:
        logger.exception("Initial account fetch failed — check credentials")
        raise SystemExit("Initial fetch failed")

    # placeholder loop
    while True:
        try:
            accts = client.list_accounts()
            logger.info(f"Heartbeat: accounts={len(accts) if accts is not None else 'unknown'}")
            sleep(10)
        except Exception:
            logger.exception("Error in loop; sleeping 5s")
            sleep(5)

if __name__ == "__main__":
    main()
