# debug_jwt_test.py
import os
import time
import base64
import json
import requests
from loguru import logger
import jwt  # pyjwt

logger.remove()
logger.add(lambda m: print(m, end=""))

# Load environment variables
ORG_ID = os.environ.get("COINBASE_ORG_ID", "")
API_KEY = os.environ.get("COINBASE_API_KEY", "")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")

# Fix escaped newlines if needed
if "\\n" in PEM_RAW:
    PEM = PEM_RAW.replace("\\n", "\n")
else:
    PEM = PEM_RAW

# Detect if COINBASE_API_KEY is full path
if "organizations/" in API_KEY:
    sub = API_KEY  # full path
else:
    sub = f"organizations/{ORG_ID}/apiKeys/{API_KEY}"

logger.info(f"Using sub for JWT: {sub}")

# JWT payload
iat = int(time.time())
exp = iat + 300  # 5 min expiry
payload = {
    "sub": sub,
    "iat": iat,
    "exp": exp,
    "jti": str(iat)
}

# Generate JWT
try:
    token = jwt.encode(payload, PEM, algorithm="ES256")
    logger.info(f"✅ JWT generated successfully. Preview (first 100 chars): {token[:100]}")
except Exception as e:
    logger.error(f"Failed to generate JWT: {type(e).__name__}: {e}")
    raise SystemExit(1)

# Test Coinbase API
url = "https://api.coinbase.com/api/v3/brokerage/accounts"
headers = {
    "Authorization": f"Bearer {token}",
    "CB-VERSION": "2025-11-13"
}

try:
    resp = requests.get(url, headers=headers)
    logger.info(f"Coinbase API status: {resp.status_code}")
    logger.info(f"Response body (first 500 chars):\n{resp.text[:500]}")
except Exception as e:
    logger.error(f"Failed to call Coinbase API: {type(e).__name__}: {e}")
