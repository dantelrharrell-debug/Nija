import os
from app.nija_client import CoinbaseClient

# Initialize client
client = CoinbaseClient(
    api_key=os.environ["COINBASE_API_KEY"],
    org_id=os.environ["COINBASE_ORG_ID"],
    pem=os.environ["COINBASE_PEM_CONTENT"]
)

# Test request (replace with any Coinbase endpoint)
response = client.request("GET", "https://api.coinbase.com/v2/accounts")
print(response.status_code, response.text)

import time, sys
from loguru import logger

logger.remove()
logger.add(sys.stdout, level="INFO", enqueue=True)

logger.info("Nija bot starting... (main.py)")

try:
    from app.start_bot_main import start_bot_main
    logger.info("Imported start_bot_main OK")
except Exception as e:
    logger.exception("Failed to import/start bot: %s", e)

# Start bot
try:
    start_bot_main()
except Exception as e:
    logger.exception("Bot crashed: {}", e)

# Keep container alive if bot crashes
while True:
    logger.info("heartbeat")
    sys.stdout.flush()
    time.sleep(60)
