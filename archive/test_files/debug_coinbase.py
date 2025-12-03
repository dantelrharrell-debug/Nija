import os
import time
import jwt
import requests
from loguru import logger

# ---------------------------
# CONFIG - make sure these are EXACT
# ---------------------------
ORG_ID = os.environ.get("COINBASE_ORG_ID")          # Your Coinbase org ID
PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")  # Your EC private key
API_KEY_ID = os.environ.get("COINBASE_API_KEY")       # Your API key ID (kid)

if not ORG_ID or not PEM_CONTENT or not API_KEY_ID:
    logger.error("Missing one of the required env variables: ORG_ID, PEM_CONTENT, API_KEY_ID")
    exit(1)

# ---------------------------
# Generate JWT
# ---------------------------
now = int(time.time())
payload = {
    "iat": now,
    "exp": now + 300,   # 5 minutes
    "sub": ORG_ID
}

headers = {
    "kid": API_KEY_ID
}

try:
    token = jwt.encode(payload, PEM_CONTENT, algorithm="ES256", headers=headers)
    logger.info(f"Generated JWT preview: {token[:50]}...")
except Exception as e:
    logger.error(f"Failed to generate JWT: {e}")
    exit(1)

# ---------------------------
# Test request to Coinbase
# ---------------------------
url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{ORG_ID}/accounts"
headers_req = {
    "Authorization": f"Bearer {token}",
    "CB-VERSION": "2023-11-13"
}

try:
    resp = requests.get(url, headers=headers_req)
    logger.info(f"Status Code: {resp.status_code}")
    logger.info(f"Response Body: {resp.text}")
except Exception as e:
    logger.error(f"Failed to make request: {e}")
