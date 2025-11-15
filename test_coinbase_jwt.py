import os
import jwt
import time
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Setup logger
logger.remove()
logger.add(lambda msg: print(msg, flush=True), level="INFO")
logger.info("Starting Coinbase JWT test...")

# Load env variables
API_KEY = os.environ.get("COINBASE_API_KEY")
ORG_ID = os.environ.get("COINBASE_ORG_ID")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT")

if not API_KEY or not ORG_ID or not PEM_RAW:
    logger.error("One of COINBASE_API_KEY, COINBASE_ORG_ID, or COINBASE_PEM_CONTENT is missing")
    exit(1)

# Clean PEM formatting
PEM_CLEAN = PEM_RAW.replace("\\n", "\n")

try:
    private_key = serialization.load_pem_private_key(
        PEM_CLEAN.encode(),
        password=None,
        backend=default_backend()
    )
except Exception as e:
    logger.exception("Failed to load PEM key")
    exit(1)

# Generate JWT for testing
iat = int(time.time())
exp = iat + 300  # 5 minutes expiration
payload = {
    "iat": iat,
    "exp": exp,
    "sub": ORG_ID
}

try:
    token = jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": API_KEY})
    logger.info(f"Generated JWT (first 50 chars): {token[:50]}...")
except Exception as e:
    logger.exception("Failed to generate JWT")
    exit(1)

# Test Coinbase endpoint
url = "https://api.coinbase.com/v2/accounts"
headers = {"Authorization": f"Bearer {token}"}

try:
    response = requests.get(url, headers=headers)
    logger.info(f"Status Code: {response.status_code}")
    logger.info(f"Response: {response.text}")
except Exception as e:
    logger.exception("Failed to connect to Coinbase API")
