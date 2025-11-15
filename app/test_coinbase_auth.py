import os
import jwt
import time
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger

logger.remove()
logger.add(lambda msg: print(msg, flush=True), level="INFO")

# Load env variables
API_KEY = os.environ.get("COINBASE_API_KEY")
ORG_ID = os.environ.get("COINBASE_ORG_ID")
PEM = os.environ.get("COINBASE_PEM_CONTENT")

# Check lengths
logger.info(f"API_KEY len: {len(API_KEY) if API_KEY else 'MISSING'}")
logger.info(f"ORG_ID len: {len(ORG_ID) if ORG_ID else 'MISSING'}")
logger.info(f"PEM len: {len(PEM) if PEM else 'MISSING'}")

# Clean PEM if needed
PEM_clean = PEM.replace("\\n", "\n") if PEM else None

# Generate JWT
try:
    private_key = serialization.load_pem_private_key(
        PEM_clean.encode(), password=None, backend=default_backend()
    )
    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "sub": ORG_ID,
    }
    token = jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": ORG_ID})
    logger.info(f"JWT generated successfully: {token[:50]}...")
except Exception as e:
    logger.exception("Failed to generate JWT")

# Test Coinbase API
try:
    headers = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-15"}
    response = requests.get("https://api.coinbase.com/v2/accounts", headers=headers)
    logger.info(f"Coinbase test status: {response.status_code}")
    if response.status_code != 200:
        logger.error(f"API response: {response.text}")
except Exception as e:
    logger.exception("Coinbase API request failed")
