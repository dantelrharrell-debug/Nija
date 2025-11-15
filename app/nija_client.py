# app/nija_client.py

import os
import time
import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger

# -----------------------------
# Setup logger
# -----------------------------
logger.remove()
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

# -----------------------------
# Load PEM and generate JWT
# -----------------------------
with open(os.environ["COINBASE_PEM_PATH"], "rb") as f:
    private_key = serialization.load_pem_private_key(
        f.read(),
        password=None,
        backend=default_backend()
    )

iat = int(time.time())
payload = {
    "sub": os.environ["COINBASE_ORG_ID"],  # MUST be your Org ID
    "iat": iat,
    "exp": iat + 300  # JWT valid for 5 minutes
}

COINBASE_JWT = jwt.encode(payload, private_key, algorithm="ES256")
logger.info(f"Generated Coinbase JWT: {COINBASE_JWT[:50]}...")

# -----------------------------
# Test request to Coinbase
# -----------------------------
headers = {
    "Authorization": f"Bearer {COINBASE_JWT}",
    "CB-VERSION": "2025-01-01"
}

try:
    resp = requests.get("https://api.coinbase.com/v2/accounts", headers=headers)
    logger.info(f"Coinbase status: {resp.status_code}, response: {resp.text[:200]}...")
except Exception as e:
    logger.error(f"Coinbase request failed: {e}")
