# main.py
import os
from loguru import logger
from app.nija_client import CoinbaseClient

# Load environment or hardcode for testing
api_key = os.environ.get("COINBASE_API_KEY", "your_api_key_here")
org_id = os.environ.get("COINBASE_ORG_ID", "your_org_id_here")
pem = os.environ.get("COINBASE_PEM_CONTENT", """-----BEGIN EC PRIVATE KEY-----
YOUR_PEM_HERE
-----END EC PRIVATE KEY-----""")
kid = os.environ.get("COINBASE_KID", "your_kid_here")  # must be a string

try:
    logger.info("Nija bot starting... (main.py)")
    client = CoinbaseClient(api_key=api_key, org_id=org_id, pem=pem, kid=kid)
    logger.info("CoinbaseClient initialized")

    # Test fetch accounts
    status, resp = client.request_auto("GET", "/v2/accounts")
    logger.info(f"Coinbase API test status: {status}")
    logger.info(f"API response: {resp}")

except Exception as e:
    logger.exception("Failed to start Coinbase client or fetch accounts")
    raise e

# Example start_bot_main
def start_bot_main(client):
    logger.info("Bot initialization started")
    import time
    try:
        while True:
            # Example heartbeat
            logger.info("Bot heartbeat - still running")
            time.sleep(10)
    except KeyboardInterrupt:
        logger.info("Bot stopped manually")

# Run bot
start_bot_main(client)
