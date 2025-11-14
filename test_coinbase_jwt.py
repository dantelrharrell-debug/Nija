# test_jwt_coinbase.py
import os
import time
import jwt  # pyjwt
import requests
from loguru import logger

logger.remove()
logger.add(lambda m: print(m, end=""))

# Load environment
ORG_ID = os.environ.get("COINBASE_ORG_ID")
API_KEY = os.environ.get("COINBASE_API_KEY")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")

# Fix escaped newlines
PEM = PEM_RAW.replace("\\n", "\n") if "\\n" in PEM_RAW else PEM_RAW

# Detect if API_KEY is full path
if "organizations/" in API_KEY:
    sub = API_KEY
else:
    sub = f"organizations/{ORG_ID}/apiKeys/{API_KEY}"

logger.info(f"ORG_ID: {ORG_ID}")
logger.info(f"API_KEY (first 10 chars): {API_KEY[:10]}...")
logger.info(f"JWT sub claim: {sub}")
logger.info(f"PEM preview: {PEM[:30]}...{PEM[-30:]}")

# Generate JWT
payload = {
    "sub": sub,
    "iat": int(time.time()),
    "exp": int(time.time()) + 300  # 5 min
}
token = jwt.encode(payload, PEM, algorithm="ES256")

logger.info(f"JWT preview (first 50 chars): {token[:50]}")

# Minimal test request: list accounts
url = "https://api.coinbase.com/v2/accounts"
headers = {
    "Authorization": f"Bearer {token}",
    "CB-VERSION": "2025-11-13"
}

response = requests.get(url, headers=headers)
logger.info(f"Status Code: {response.status_code}")
logger.info(f"Response Body: {response.text[:500]}")  # first 500 chars
