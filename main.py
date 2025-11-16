# main.py  (Option A - nija_client.py at repo root)
import os
import time
from loguru import logger
from nija_client import CoinbaseClient, load_private_key

logger.remove()
logger.add(lambda m: print(m, end=""), level="INFO")

API_KEY_ID = os.environ.get("COINBASE_API_KEY")
ORG_ID = os.environ.get("COINBASE_ORG_ID")
PEM_RAW = os.environ.get("COINBASE_PEM", "")
PEM_PATH = os.environ.get("COINBASE_PEM_PATH", "")

def start_bot_main():
    logger.info("Nija bot starting...")

    private_key = load_private_key(PEM_RAW, PEM_PATH)
    client = CoinbaseClient(api_key_id=API_KEY_ID, org_id=ORG_ID, private_key=private_key)

    accounts = client.get_accounts()
    if accounts:
        logger.info("Startup accounts OK")
    else:
        logger.warning("Startup accounts fetch failed")

    try:
        while True:
            accounts = client.get_accounts()
            if accounts:
                logger.info("heartbeat: accounts OK")
            else:
                logger.warning("heartbeat: accounts failed")
            logger.info("heartbeat")
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.exception("Unexpected crash: %s", e)

if __name__ == "__main__":
    start_bot_main()
