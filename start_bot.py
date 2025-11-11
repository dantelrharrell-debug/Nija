# start_bot.py
import os
from dotenv import load_dotenv
from nija_client import CoinbaseClient
from loguru import logger
import requests
import time
import hmac
import hashlib

# Load environment variables from .env
load_dotenv()

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # optional

BASE_URL = "https://api.coinbase.com/v2"

def test_api_keys():
    """Quick test to see if Coinbase API keys are valid."""
    timestamp = str(int(time.time()))
    method = "GET"
    request_path = "/accounts"
    body = ""

    message = timestamp + method + request_path + body
    signature = hmac.new(
        API_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-VERSION": "2025-11-11",
    }

    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE

    try:
        response = requests.get(BASE_URL + request_path, headers=headers)
        logger.info(f"API Test Status Code: {response.status_code}")
        logger.info(f"API Test Response: {response.text}")
        return response.status_code == 200
    except Exception as e:
        logger.error(f"API test failed: {e}")
        return False

def main():
    logger.info("Starting Nija loader (robust).")

    if not test_api_keys():
        logger.error("❌ Coinbase API keys invalid or unauthorized. Check your .env file.")
        return

    # Initialize CoinbaseClient
    try:
        client = CoinbaseClient(advanced=True)  # tries CDP mode
        logger.info("✅ CoinbaseClient initialized successfully in advanced/CDP mode.")
    except Exception as e:
        logger.error(f"Failed to init CoinbaseClient in advanced mode: {e}")
        logger.info("Falling back to regular Coinbase client...")
        try:
            client = CoinbaseClient(advanced=False)  # fallback
            logger.info("✅ CoinbaseClient initialized successfully in regular mode.")
        except Exception as e:
            logger.error(f"Failed to init CoinbaseClient in fallback mode: {e}")
            return

    # Fetch accounts with fallback
    try:
        accounts = client.fetch_advanced_accounts() if client.advanced else client.get_accounts()
        if not accounts:
            logger.warning("No accounts found. Trying fallback endpoint...")
            if client.advanced:
                accounts = client.get_accounts()
                if not accounts:
                    logger.error("❌ No accounts found in either CDP or regular endpoints.")
                    return
        logger.info(f"Accounts fetched successfully: {accounts}")
    except Exception as e:
        logger.error(f"Failed to fetch accounts: {e}")

if __name__ == "__main__":
    main()
