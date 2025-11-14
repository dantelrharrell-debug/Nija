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

# 2️⃣ Fix PEM newlines if Railway/cloud env replaced "\n" with literal
if PEM_RAW and "\\n" in PEM_RAW:
    PEM_RAW = PEM_RAW.replace("\\n", "\n")

# Optional debug
logger.info(f"PEM length: {len(PEM_RAW) if PEM_RAW else 'None'}")

# 3️⃣ JWT token generation for Coinbase Advanced
def generate_jwt():
    if not PEM_RAW:
        raise ValueError("❌ COINBASE_PEM_CONTENT not set.")
    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,  # 1 minute expiry
        "sub": ORG_ID
    }
    try:
        token = jwt.encode(payload, PEM_RAW, algorithm="ES256")
        logger.success("✅ JWT generated successfully")
        return token
    except Exception as e:
        logger.error(f"❌ JWT generation failed: {e}")
        raise

# 4️⃣ Coinbase API wrapper
class CoinbaseClient:
    BASE_URL = "https://api.coinbase.com"

    def __init__(self):
        self.jwt = generate_jwt()
        self.headers = {
            "Authorization": f"Bearer {self.jwt}",
            "CB-VERSION": "2025-11-13"
        }

    def get_accounts(self):
        url = f"{self.BASE_URL}/v2/accounts"
        resp = requests.get(url, headers=self.headers)
        if resp.status_code != 200:
            raise Exception(f"Coinbase API error {resp.status_code}: {resp.text}")
        return resp.json()["data"]

# 5️⃣ Test connection
def test_accounts():
    try:
        client = CoinbaseClient()
        accounts = client.get_accounts()
        logger.success("✅ Coinbase accounts fetched successfully:")
        for a in accounts:
            logger.info(f"- {a['id']} | {a['name']} | Balance: {a['balance']['amount']} {a['balance']['currency']}")
    except Exception as e:
        logger.error(f"❌ Coinbase auth failed: {e}")

# 6️⃣ Run directly
if __name__ == "__main__":
    test_accounts()
