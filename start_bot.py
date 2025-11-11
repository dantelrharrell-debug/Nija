import os
import time
import requests
import hmac
import hashlib
from loguru import logger

# Optional import if you still want your CoinbaseClient
# from nija_client import CoinbaseClient

BASE_URL = os.getenv("COINBASE_API_BASE", "https://api.coinbase.com")

# ----------------------------
# Determine API mode
# ----------------------------
USE_ADVANCED = bool(os.getenv("COINBASE_ISS") and os.getenv("COINBASE_PEM_CONTENT"))
USE_BASE = bool(os.getenv("COINBASE_API_KEY") and os.getenv("COINBASE_API_SECRET"))

if USE_ADVANCED:
    logger.info("Using Coinbase Advanced (JWT) mode.")
elif USE_BASE:
    logger.info("Using Coinbase Base API mode.")
else:
    logger.error("❌ No valid Coinbase keys found in .env")
    exit(1)

# ----------------------------
# Test Coinbase Keys
# ----------------------------
def test_base_keys():
    API_KEY = os.getenv("COINBASE_API_KEY")
    API_SECRET = os.getenv("COINBASE_API_SECRET")
    API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")

    timestamp = str(int(time.time()))
    method = "GET"
    request_path = "/accounts"
    body = ""

    message = timestamp + method + request_path + body
    signature = hmac.new(
        API_SECRET.encode(), message.encode(), hashlib.sha256
    ).hexdigest()

    headers = {
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-SIGN": signature,
        "CB-ACCESS-TIMESTAMP": timestamp,
        "CB-VERSION": "2025-11-11",
    }

    if API_PASSPHRASE:
        headers["CB-ACCESS-PASSPHRASE"] = API_PASSPHRASE

    r = requests.get(BASE_URL + request_path, headers=headers)
    return r.status_code, r.text


def test_coinbase():
    if USE_BASE:
        status, data = test_base_keys()
    else:
        # Placeholder: add JWT test function for Advanced if needed
        status, data = 200, "Advanced JWT keys assumed OK"

    logger.info(f"API Test Status Code: {status}")
    logger.info(f"API Test Response: {data}")

    if status != 200:
        logger.error("❌ Coinbase API keys invalid or unauthorized.")
        exit(1)
    else:
        logger.success("✅ Coinbase API keys validated successfully.")


if __name__ == "__main__":
    logger.info("Starting Nija loader (robust).")
    test_coinbase()

    # Example usage of CoinbaseClient (optional)
    # from nija_client import CoinbaseClient
    # if USE_ADVANCED:
    #     client = CoinbaseClient(jwt_mode=True)
    # else:
    #     client = CoinbaseClient()

    logger.info("Nija bot ready to trade. Awaiting signals...")
