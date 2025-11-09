# nija_app.py
import os
import sys
import time
from loguru import logger

# ✅ Import the correct CoinbaseClient
from nija_coinbase_client import CoinbaseClient

# Load environment variables
if os.path.exists(".env"):
    try:
        from dotenv import load_dotenv
        load_dotenv(".env")
        logger.info(".env loaded")
    except Exception:
        logger.warning("python-dotenv not installed, skipping .env load")

# Initialize Coinbase Client
try:
    client = CoinbaseClient(
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET"),
        api_passphrase=os.getenv("COINBASE_API_PASSPHRASE"),
        base_url=os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")
    )
    logger.info("CoinbaseClient initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize CoinbaseClient: {e}")
    sys.exit(1)

# Example function: list accounts
def list_accounts():
    try:
        accounts = client.get_accounts()  # or the correct method in your client
        for acc in accounts:
            logger.info(f"Account: {acc['name']} | Balance: {acc['balance']['amount']} {acc['balance']['currency']}")
    except Exception as e:
        logger.error(f"Error fetching accounts: {e}")

# Example function: live trading loop placeholder
def live_trading_loop():
    logger.info("Starting live trading loop...")
    while True:
        try:
            # Placeholder for your trading logic
            # e.g., signals = client.get_signals()
            logger.info("Checking for trading signals...")
            time.sleep(5)  # Replace with your actual trading interval
        except KeyboardInterrupt:
            logger.info("Live trading stopped by user")
            break
        except Exception as e:
            logger.error(f"Error in trading loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    list_accounts()          # Optional: list accounts on start
    live_trading_loop()      # Start live trading
