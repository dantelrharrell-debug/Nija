# main.py (replace the relevant parts)
import os, sys, time
from loguru import logger
from datetime import datetime
from app.nija_client import CoinbaseClient

logger.remove()
logger.add(sys.stdout, level="INFO", enqueue=True)
logger.info("Nija bot starting... (main.py)")

# load env values used below
api_key = os.environ.get("COINBASE_API_KEY")
org_id = os.environ.get("COINBASE_ORG_ID")
pem = os.environ.get("COINBASE_PEM_CONTENT")  # or COINBASE_PEM_B64 base64
kid = os.environ.get("COINBASE_JWT_KID")     # the key id (UUID) from Coinbase
sandbox = os.environ.get("SANDBOX", "false").lower() in ("1", "true", "yes")

try:
    # NOTE: pass jwt_kid= not kid=
    client = CoinbaseClient(api_key=api_key, org_id=org_id, pem=pem, jwt_kid=kid)
    logger.info("CoinbaseClient initialized")
except Exception as e:
    logger.exception("Failed to init CoinbaseClient")
    # if client cannot initialize, exit (so you can see the error and fix env)
    sys.exit(1)

# optional quick test against sandbox or API
try:
    # if you want sandbox test: client.sandbox_accounts()
    resp = client.sandbox_accounts() if sandbox else client.request("GET", "https://api.coinbase.com/v2/accounts")
    logger.info(f"Coinbase API test status: {resp.status_code}")
    logger.info(f"API response (truncated): {resp.text[:400]}")
except Exception as e:
    logger.exception("Coinbase test request failed")

# Import and pass client into starter (start_bot_main expects client param)
try:
    from app.start_bot_main import start_bot_main
    logger.info("Imported start_bot_main OK")
    start_bot_main(client)   # <--- pass the client instance
except Exception as e:
    logger.exception("Bot crashed during start")
    # keep process alive for debugging, or exit if you prefer
    while True:
        logger.info("heartbeat")
        time.sleep(60)
