# ./app/nija_client.py
# Python 3.9+ recommended. Requires: pyjwt, cryptography, requests, loguru

import os
import time
import datetime
import jwt
import requests
import base64
import json
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -----------------------
# Logger setup
logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

# -----------------------
# Environment variables
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_JWT_KID = os.getenv("COINBASE_JWT_KID")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
SANDBOX = os.getenv("SANDBOX", "1")  # default to sandbox if unset

# Check for missing vars
required_vars = {
    "COINBASE_API_KEY": COINBASE_API_KEY,
    "COINBASE_PEM_CONTENT": COINBASE_PEM_CONTENT,
    "COINBASE_JWT_KID": COINBASE_JWT_KID,
    "COINBASE_ORG_ID": COINBASE_ORG_ID
}
for k, v in required_vars.items():
    if not v:
        logger.error(f"Missing environment variable: {k}")
        raise ValueError(f"Missing environment variable: {k}")

# -----------------------
# Load private key
try:
    private_key = serialization.load_pem_private_key(
        COINBASE_PEM_CONTENT.encode("utf-8"),
        password=None,
        backend=default_backend()
    )
except Exception as e:
    logger.error(f"Failed to load PEM: {e}")
    raise

# -----------------------
# Build JWT payload and headers
now = int(time.time())
payload = {
    "sub": COINBASE_API_KEY,
    "iat": now,
    "exp": now + 300  # 5 minutes
}
headers_jwt = {
    "alg": "ES256",
    "kid": COINBASE_JWT_KID
}

# Encode JWT
try:
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
    logger.info(f"Generated JWT (preview): {token[:50]}...")
except Exception as e:
    logger.error(f"Failed to encode JWT: {e}")
    raise

# -----------------------
# Verify JWT structure
def verify_jwt_struct(token):
    try:
        header_b64, payload_b64, _ = token.split(".")
        header = json.loads(base64.urlsafe_b64decode(header_b64 + "=="))
        payload_decoded = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
        return header, payload_decoded
    except Exception as e:
        logger.error(f"Failed to decode JWT: {e}")
        raise

header, payload_decoded = verify_jwt_struct(token)
logger.info(f"JWT header.kid: {header.get('kid')}")
logger.info(f"JWT payload.sub: {payload_decoded.get('sub')}")
logger.info(f"Server UTC time: {datetime.datetime.utcnow().isoformat()}")

# -----------------------
# Test Coinbase API
BASE = "https://api-public.sandbox.pro.coinbase.com" if SANDBOX == "1" else "https://api.pro.coinbase.com"
headers_req = {"Authorization": f"Bearer {token}"}

try:
    r = requests.get(f"{BASE}/accounts", headers=headers_req)
    logger.info(f"Coinbase /accounts status: {r.status_code}")
    logger.info(f"Coinbase /accounts response: {r.text}")
except Exception as e:
    logger.error(f"API request failed: {e}")
