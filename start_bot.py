# start_bot.py
import os
from loguru import logger
from app.nija_client import CoinbaseClient  # your robust client

# --------------------------
# Load environment (for local dev)
# --------------------------
if os.path.exists(".env"):
    try:
        from dotenv import load_dotenv
        load_dotenv(".env")
        logger.info(".env loaded for local development")
    except Exception:
        logger.warning("python-dotenv not installed, skipping .env load")

# --------------------------
# Initialize logger
# --------------------------
logger.remove()
logger.add(lambda msg: print(msg, end=""), level=os.getenv("LOG_LEVEL", "INFO"))

# --------------------------
# Check environment variables for debugging
# --------------------------
logger.info(f"COINBASE_API_KEY: {os.getenv('COINBASE_API_KEY')}")
logger.info(f"COINBASE_API_KEY_ADVANCED: {os.getenv('COINBASE_API_KEY_ADVANCED')}")
logger.info(f"COINBASE_BASE: {os.getenv('COINBASE_BASE')}")

# --------------------------
# Initialize Coinbase client
# --------------------------
try:
    client = CoinbaseClient(
        advanced=True,          # True for CDP / service key, False for classic
        debug=os.getenv("DEBUG", "False").lower() in ["true", "1"]
    )
    logger.info("CoinbaseClient successfully initialized!")
except AttributeError as ae:
    logger.error(f"Initialization failed with AttributeError: {ae}")
except Exception as e:
    logger.error(f"Initialization failed with unexpected exception: {e}")

# --------------------------
# Optional: Test fetching accounts
# --------------------------
try:
    if client.advanced:
        accounts = client.fetch_advanced_accounts()
    else:
        accounts = client.fetch_spot_accounts()
    logger.info(f"Fetched {len(accounts)} accounts successfully.")
except Exception as e:
    logger.warning(f"Failed to fetch accounts: {e}")

# --------------------------
# Ready to start trading loop
# --------------------------
logger.info("Nija bot is ready. Waiting for signals...")
