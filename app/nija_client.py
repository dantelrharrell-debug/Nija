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
logger.add(lambda m: print(m, end=""), level="INFO")

# -----------------------
# Environment variables
API_KEY = os.getenv("COINBASE_API_KEY")          # e.g., "organizations/{org_id}/apiKeys/{key_id}"
PRIVATE_PEM = os.getenv("COINBASE_PEM_CONTENT") # full PEM string including BEGIN/END
KEY_ID = os.getenv("COINBASE_JWT_KID")          # key id
ORG_ID = os.getenv("COINBASE_ORG_ID")           # org id
SANDBOX = os.getenv("SANDBOX", "1")             # "1" for sandbox, "0" for live

# -----------------------
# Sanity checks
if not all([API_KEY, PRIVATE_PEM, KEY_ID, ORG_ID]):
    logger.error("One or more Coinbase env vars are missing! Please check COINBASE_API_KEY, COINBASE_PEM_CONTENT, COINBASE_JWT_KID, COINBASE_ORG_ID")
    raise SystemExit

# -----------------------
# Load private key
private_key = serialization.load_pem_private_key(
    PRIVATE_PEM.encode("utf-8"),
    password=None,
    backend=default_backend()
)

# -----------------------
# Detect server clock skew
server_utc = datetime.datetime.utcnow()
logger.info(f"Server UTC time: {server_utc.isoformat()}")

# Build claims
now = int(time.time())
# Add skew correction if needed (Coinbase allows ±5 sec safely)
CLOCK_SKEW = int(os.getenv("COINBASE_CLOCK_SKEW", 0))
payload = {
    "sub": API_KEY,
    "iat": now + CLOCK_SKEW,
    "exp": now + 300 + CLOCK_SKEW  # expire in 5 mins
}

# Build headers
headers_jwt = {
    "alg": "ES256",
    "kid": KEY_ID
}

# Encode JWT
token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
logger.info(f"Generated JWT: {token[:50]}...")

# -----------------------
# Verify JWT structure
def verify_jwt_struct(token):
    header_b64, payload_b64, _ = token.split(".")
    header = json.loads(base64.urlsafe_b64decode(header_b64 + "=="))
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    return header, payload

header, payload_decoded = verify_jwt_struct(token)
logger.info("JWT header.kid: " + str(header.get("kid")))
logger.info("JWT payload.sub: " + str(payload_decoded.get("sub")))
logger.info("JWT iat: " + str(payload_decoded.get("iat")))
logger.info("JWT exp: " + str(payload_decoded.get("exp")))

# -----------------------
# Coinbase endpoint
BASE = "https://api-public.sandbox.pro.coinbase.com" if SANDBOX == "1" else "https://api.pro.coinbase.com"
headers_req = {"Authorization": f"Bearer {token}"}

# -----------------------
# Test /accounts
r = requests.get(f"{BASE}/accounts", headers=headers_req)
logger.info(f"Sandbox /accounts response: {r.status_code} {r.text[:200]}...")
