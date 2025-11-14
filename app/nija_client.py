# app/nija_client.py

import os
import time
import jwt
import requests
from loguru import logger

# 1️⃣ Load environment variables
ORG_ID = os.environ.get("COINBASE_ORG_ID")
API_KEY = os.environ.get("COINBASE_API_KEY")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT")

if not ORG_ID or not API_KEY or not PEM_RAW:
    logger.error("❌ One or more required environment variables are missing!")
    logger.error(f"ORG_ID: {ORG_ID}, API_KEY: {API_KEY}, PEM length: {len(PEM_RAW) if PEM_RAW else 0}")
    raise SystemExit("Missing environment variables. Exiting.")

# 2️⃣ Fix PEM newlines
PEM_FIXED = PEM_RAW.replace("\\n", "\n").replace("COINBASE_PEM_CONTENT=", "").strip()
logger.info(f"PEM length after fix: {len(PEM_FIXED)}")

# 3️⃣ Generate JWT for Coinbase Advanced
def generate_jwt():
    try:
        payload = {
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,  # 5 min expiry
            "sub": ORG_ID
        }
        token = jwt.encode(payload, PEM_FIXED, algorithm="ES256")
        logger.info(f"✅ JWT generated successfully (preview): {str(token)[:50]}...")
        return token
    except Exception as e:
        logger.error(f"❌ JWT generation failed: {e}")
        return None

JWT_TOKEN = generate_jwt()
if not JWT_TOKEN:
    raise SystemExit("Cannot continue without valid JWT.")

# 4️⃣ Coinbase REST call
BASE_URL = "https://api.coinbase.com/v2"  # Advanced API base
HEADERS = {
    "Authorization": f"Bearer {JWT_TOKEN}",
    "CB-VERSION": "2025-11-13"
}

def fetch_accounts():
    url = f"{BASE_URL}/accounts"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            data = response.json()
            logger.success("✅ Accounts fetched successfully:")
            for a in data.get("data", []):
                logger.info(f"- {a.get('id')} | {a.get('name')} | {a.get('balance')}")
        else:
            logger.error(f"❌ Coinbase API returned {response.status_code}: {response.text}")
    except Exception as e:
        logger.error(f"❌ Error fetching accounts: {e}")

# 5️⃣ Run directly
if __name__ == "__main__":
    fetch_accounts()
