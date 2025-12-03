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
KEY_ID = os.getenv("COINBASE_JWT_KID")          # key id (UUID or full path depending on Coinbase)

# -----------------------
# Load private key
private_key = serialization.load_pem_private_key(
    PRIVATE_PEM.encode("utf-8"),
    password=None,
    backend=default_backend()
)

# -----------------------
# Build claims
now = int(time.time())
payload = {
    "sub": API_KEY,
    "iat": now,
    "exp": now + 300  # expire in 5 mins
}

# Build headers
headers_jwt = {
    "alg": "ES256",
    "kid": KEY_ID
}

# Encode JWT
token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
logger.info(f"Generated JWT: {token}")

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
logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())

# -----------------------
# Test sandbox API
BASE = "https://api-public.sandbox.pro.coinbase.com"
headers_req = {"Authorization": f"Bearer {token}"}

r = requests.get(f"{BASE}/accounts", headers=headers_req)
print("Sandbox /accounts response:", r.status_code, r.text)
