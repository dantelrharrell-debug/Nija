# nija_render_worker.py
import os
from time import sleep
from loguru import logger
from nija_client import CoinbaseClient

logger.add("/tmp/worker.log", rotation="10 MB", retention="7 days", level="INFO")

def dump_env_snippet():
    keys = ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_API_PASSPHRASE",
            "COINBASE_PEM_CONTENT", "COINBASE_ORG_ID", "COINBASE_ACCOUNT_ID", "LIVE_TRADING"]
    logger.info("ENV snapshot:")
    for k in keys:
        v = os.getenv(k)
        if not v:
            logger.warning(f"{k}: MISSING")
        else:
            logger.info(f"{k}: present, startswith: {v.strip().splitlines()[0][:40]!r}")

def main():
    logger.info("nija_render_worker starting up")
    dump_env_snippet()

    try:
        client = CoinbaseClient()
    except Exception as e:
        logger.exception("Failed to initialize CoinbaseClient — worker exiting")
        raise SystemExit("Coinbase auth init failed")

    # quick test call
    try:
        accounts = client.list_accounts()
        logger.info(f"Connected — fetched accounts count: {len(accounts) if accounts is not None else 'unknown'}")
    except Exception:
        logger.exception("Initial account fetch failed — check credentials and SDK compatibility")
        raise SystemExit("Initial Coinbase fetch failed")

    # Main placeholder loop
    while True:
        try:
            accounts = client.list_accounts()
            logger.info(f"Heartbeat: accounts={len(accounts) if accounts is not None else 'unknown'}")
            sleep(10)
        except Exception:
            logger.exception("Error in trading loop; sleeping 5s")
            sleep(5)

if __name__ == "__main__":
    main()
