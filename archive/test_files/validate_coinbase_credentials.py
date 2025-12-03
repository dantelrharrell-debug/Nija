# validate_coinbase_credentials.py
# Python 3.9+ recommended. Requires: pyjwt, requests, loguru, cryptography

import os
import jwt
import time
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logger.remove()
logger.add(lambda msg: print(msg, end=''))

# ----------------------
# Load Environment Variables
# ----------------------
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # Raw PEM as string
COINBASE_JWT_KID = os.getenv("COINBASE_JWT_KID")
COINBASE_BASE_URL = os.getenv("SANDBOX") == "1" and "https://api-public.sandbox.pro.coinbase.com" or "https://api.pro.coinbase.com"

if not all([COINBASE_API_KEY, COINBASE_ORG_ID, COINBASE_PEM_CONTENT, COINBASE_JWT_KID]):
    logger.error("Missing one or more Coinbase credentials in environment variables.")
    exit(1)

# ----------------------
# Prepare PEM
# ----------------------
try:
    private_key = serialization.load_pem_private_key(
        COINBASE_PEM_CONTENT.encode("utf-8"),
        password=None,
        backend=default_backend()
    )
    logger.info("PEM loaded successfully.")
except Exception as e:
    logger.error(f"Failed to load PEM: {e}")
    exit(1)

# ----------------------
# Generate JWT
# ----------------------
try:
    iat = int(time.time())
    exp = iat + 300  # 5 minutes
    payload = {
        "iss": COINBASE_ORG_ID,
        "iat": iat,
        "exp": exp
    }
    jwt_token = jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": COINBASE_JWT_KID})
    logger.info(f"JWT generated successfully: {jwt_token[:50]}...")
except Exception as e:
    logger.error(f"Failed to generate JWT: {e}")
    exit(1)

# ----------------------
# Test Coinbase API
# ----------------------
try:
    headers = {
        "Authorization": f"Bearer {jwt_token}",
        "CB-VERSION": "2025-11-15"  # adjust if needed
    }
    url = f"{COINBASE_BASE_URL}/accounts"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        logger.success("✅ Credentials are valid! Coinbase API accessible.")
        logger.info(response.json())
    else:
        logger.error(f"❌ Unauthorized or invalid credentials! Status: {response.status_code}")
        logger.error(response.text)
except Exception as e:
    logger.error(f"API request failed: {e}")
