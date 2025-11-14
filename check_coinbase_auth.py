# check_coinbase_auth.py
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
    logger.error("❌ Missing one or more Coinbase environment variables.")
    exit(1)

# 2️⃣ Fix PEM newlines if cloud env replaced them
PEM_RAW = PEM_RAW.replace("\\n", "\n")
logger.info(f"PEM length after fix: {len(PEM_RAW)}")

# 3️⃣ Generate JWT for Coinbase Advanced REST API
def generate_jwt():
    try:
        iat = int(time.time())
        payload = {
            "sub": ORG_ID,
            "iat": iat,
            "exp": iat + 30,
            "jti": str(iat),
        }
        token = jwt.encode(payload, PEM_RAW, algorithm="ES256")
        return token
    except Exception as e:
        logger.error(f"❌ JWT generation failed: {e}")
        return None

jwt_token = generate_jwt()
if not jwt_token:
    exit(1)

logger.success("✅ JWT generated successfully:")
logger.info(jwt_token[:50] + "...")

# 4️⃣ Test Coinbase endpoint with generated JWT
headers = {"Authorization": f"Bearer {jwt_token}", "CB-VERSION": "2025-11-13"}
url = "https://api.coinbase.com/v2/accounts"

try:
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        logger.success("✅ Coinbase authentication successful!")
        accounts = response.json().get("data", [])
        for acc in accounts:
            logger.info(f"- {acc['id']} | {acc['name']} | Balance: {acc['balance']['amount']} {acc['balance']['currency']}")
    else:
        logger.error(f"❌ Coinbase auth failed. Status: {response.status_code}, Body: {response.text}")
except Exception as e:
    logger.error(f"❌ Error connecting to Coinbase: {e}")
