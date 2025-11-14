# test_coinbase_auth.py
import os
import time
import jwt
import requests
from loguru import logger

logger.remove()
logger.add(lambda m: print(m, end=""))

# Load environment variables
ORG_ID = os.environ.get("COINBASE_ORG_ID")
API_KEY = os.environ.get("COINBASE_API_KEY")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")

# Fix escaped newlines in PEM
if "\\n" in PEM_RAW:
    PEM = PEM_RAW.replace("\\n", "\n")
else:
    PEM = PEM_RAW

# Detect if API_KEY is full path
if "organizations/" in API_KEY:
    sub = API_KEY
else:
    sub = f"organizations/{ORG_ID}/apiKeys/{API_KEY}"

# Generate JWT
iat = int(time.time())
payload = {
    "sub": sub,
    "iat": iat,
    "exp": iat + 30  # short-lived token
}

try:
    token = jwt.encode(payload, PEM, algorithm="ES256")
    logger.info(f"✅ JWT generated: {token[:40]}...")
except Exception as e:
    logger.error(f"Failed to generate JWT: {type(e).__name__}: {e}")
    raise

# Make test request to Coinbase API
url = "https://api.coinbase.com/v2/accounts"
headers = {
    "Authorization": f"Bearer {token}",
    "CB-VERSION": "2025-11-13"
}

try:
    r = requests.get(url, headers=headers)
    logger.info(f"Response status: {r.status_code}")
    logger.info(f"Response body: {r.text[:500]}")  # print first 500 chars
except Exception as e:
    logger.error(f"Request failed: {type(e).__name__}: {e}")
