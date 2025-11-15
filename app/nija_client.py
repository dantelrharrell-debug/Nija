# ./app/nija_client.py
import os
import sys
import time
import datetime
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import base64
import json

# -----------------------
# Logger setup
logger.remove()
logger.add(lambda m: print(m, end=""), level="INFO")

# -----------------------
# Load environment vars
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")

if not all([COINBASE_API_KEY, COINBASE_PEM_CONTENT, COINBASE_ORG_ID]):
    logger.error("Missing Coinbase environment variables")
    sys.exit(1)

# -----------------------
# Load PEM safely
try:
    private_key = serialization.load_pem_private_key(
        COINBASE_PEM_CONTENT.encode("utf-8"),
        password=None,
        backend=default_backend()
    )
    logger.info("PEM loaded successfully")
except Exception as e:
    logger.error(f"Failed to load PEM: {e}")
    sys.exit(1)

# -----------------------
# Generate JWT
now = int(time.time())
token_payload = {
    "iat": now,
    "exp": now + 300,  # 5 min expiration
    "sub": COINBASE_API_KEY,
    "aud": "https://api.coinbase.com"
}

token_headers = {
    "alg": "ES256",
    "kid": COINBASE_ORG_ID,
    "typ": "JWT"
}

try:
    token = jwt.encode(token_payload, private_key, algorithm="ES256", headers=token_headers)
    logger.info("JWT generated successfully")
except Exception as e:
    logger.error(f"Failed to generate JWT: {e}")
    sys.exit(1)

# -----------------------
# Verify JWT structure
def verify_jwt_struct(token):
    header_b64, payload_b64, _ = token.split(".")
    header = json.loads(base64.urlsafe_b64decode(header_b64 + "=="))
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    return header, payload

header, payload = verify_jwt_struct(token)
logger.info("JWT header.kid: " + str(header.get("kid")))
logger.info("JWT payload.sub: " + str(payload.get("sub")))
logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())

# -----------------------
# Test Coinbase auth
try:
    r = requests.get(
        "https://api.coinbase.com/v2/accounts",
        headers={"Authorization": f"Bearer {token}"}
    )
    logger.info(f"Coinbase auth response code: {r.status_code}")
    logger.info(f"Coinbase auth response body: {r.text}")
except Exception as e:
    logger.error(f"Failed to contact Coinbase API: {e}")
