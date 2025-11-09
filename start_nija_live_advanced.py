import os
import time
import json
import jwt
import requests
from loguru import logger
from datetime import datetime, timedelta

# ---------------------------
# CONFIG
# ---------------------------
COINBASE_ISS = os.getenv("COINBASE_ISS")  # e.g. organizations/<org_id>/apiKeys/<key_id>
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # PEM private key string
BASE_URL = "https://api.coinbase.com/api/v3"

# ---------------------------
# JWT GENERATION
# ---------------------------
def generate_jwt():
    try:
        payload = {
            "iss": COINBASE_ISS,
            "iat": int(time.time()),
            "exp": int(time.time()) + 30  # 30 seconds expiry
        }
        token = jwt.encode(payload, COINBASE_PEM_CONTENT, algorithm="ES256")
        return token
    except Exception as e:
        logger.exception(f"Failed to generate JWT: {e}")
        return None

# ---------------------------
# API REQUEST HELPER
# ---------------------------
def api_request(path, method="GET", data=None):
    token = generate_jwt()
    if not token:
        return 500, {"error": "JWT generation failed"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    url = f"{BASE_URL}{path}"

    try:
        if method.upper() == "GET":
            resp = requests.get(url, headers=headers)
        elif method.upper() == "POST":
            resp = requests.post(url, headers=headers, json=data)
        else:
            return 400, {"error": f"Unsupported method {method}"}

        try:
            resp_data = resp.json()
        except json.JSONDecodeError:
            logger.warning(f"⚠️ JSON decode failed. Status: {resp.status_code}, Body: {resp.text}")
            resp_data = {"raw_body": resp.text}

        return resp.status_code, resp_data
    except Exception as e:
        logger.exception(f"Request failed: {e}")
        return 500, {"error": str(e)}

# ---------------------------
# FETCH ADVANCED ACCOUNTS
# ---------------------------
def fetch_accounts():
    status, data = api_request("/brokerage/accounts")  # Advanced API endpoint
    if status != 200:
        logger.error(f"❌ Failed to fetch accounts. Status: {status}")
        return status, data

    accounts = data.get("data", [])
    logger.info(f"✅ Fetched {len(accounts)} accounts.")
    return status, accounts

# ---------------------------
# MAIN BOT LOOP
# ---------------------------
def main_loop():
    logger.info("Starting Coinbase Advanced bot...")

    status, accounts = fetch_accounts()
    if status != 200 or not accounts:
        logger.error("No accounts returned. Bot will not start.")
        return

    # Example: iterate through accounts
    for acc in accounts:
        logger.info(f"Account: {acc.get('id')} - {acc.get('name')}")

    logger.info("Bot is ready to trade with fetched accounts.")

# ---------------------------
# START
# ---------------------------
if __name__ == "__main__":
    main_loop()
