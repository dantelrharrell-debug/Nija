import os
import sys
import time
from loguru import logger
from app.nija_client import CoinbaseClient

# -----------------------------
# Logger Setup
# -----------------------------
logger.remove()
logger.add(sys.stdout, level="INFO", enqueue=True)
logger.info("Nija bot starting... (main.py)")

# -----------------------------
# Initialize Coinbase Client
# -----------------------------
try:
    client = CoinbaseClient(
        api_key=os.environ["COINBASE_API_KEY"],
        org_id=os.environ["COINBASE_ORG_ID"],
        pem=os.environ["COINBASE_PEM_CONTENT"]
    )
    logger.info("CoinbaseClient initialized")
except Exception as e:
    logger.exception("Failed to initialize CoinbaseClient: {}", e)
    sys.exit(1)

# -----------------------------
# Optional: Test Coinbase API Connection
# -----------------------------
try:
    response = client.request("GET", "https://api.coinbase.com/v2/accounts")
    logger.info(f"Coinbase API test status: {response.status_code}")
except Exception as e:
    logger.exception("Coinbase test request failed")

# -----------------------------
# Start Bot
# -----------------------------
try:
    from app.start_bot_main import start_bot_main
    logger.info("Imported start_bot_main OK")
    start_bot_main()
except Exception as e:
    logger.exception("Bot crashed during start")

# -----------------------------
# Keep container alive if bot crashes
# -----------------------------
while True:
    logger.info("heartbeat")
    sys.stdout.flush()
    time.sleep(60)
