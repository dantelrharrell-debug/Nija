# ./app/nija_client.py

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
# Environment variables (Sandbox)
API_KEY = os.getenv("COINBASE_API_KEY")          # Sandbox key e.g., "organizations/{org_id}/apiKeys/{key_id}"
PRIVATE_PEM = os.getenv("COINBASE_PEM_CONTENT") # PEM string with BEGIN/END lines
KEY_ID = os.getenv("COINBASE_JWT_KID")          # The key ID from Coinbase dashboard
BASE_URL = "https://api-public.sandbox.pro.coinbase.com"  # Sandbox endpoint

# -----------------------
# Load private key
private_key = serialization.load_pem_private_key(
    PRIVATE_PEM.encode("utf-8"),
    password=None,
    backend=default_backend()
)

# -----------------------
# JWT generation
def generate_jwt():
    now = int(time.time())
    payload = {
        "sub": API_KEY,
        "iat": now,
        "exp": now + 300  # expires in 5 minutes
    }
    headers = {
        "alg": "ES256",
        "kid": KEY_ID
    }
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token

# -----------------------
# JWT verification (for logging)
def verify_jwt_struct(token):
    header_b64, payload_b64, _ = token.split(".")
    header = json.loads(base64.urlsafe_b64decode(header_b64 + "=="))
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    return header, payload

# -----------------------
# Make request
def c_request(method, endpoint, data=None):
    token = generate_jwt()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # Log JWT info
    header, payload = verify_jwt_struct(token)
    logger.info(f"JWT header.kid: {header.get('kid')}")
    logger.info(f"JWT payload.sub: {payload.get('sub')}")
    logger.info(f"Server UTC time: {datetime.datetime.utcnow().isoformat()}")

    url = f"{BASE_URL}{endpoint}"
    if method.lower() == "get":
        r = requests.get(url, headers=headers)
    elif method.lower() == "post":
        r = requests.post(url, json=data, headers=headers)
    else:
        raise ValueError("Method must be 'get' or 'post'")

    logger.info(f"Request URL: {url}")
    logger.info(f"Status Code: {r.status_code}")
    logger.info(f"Response: {r.text[:1000]}")  # first 1000 chars
    return r

# -----------------------
# Example usage
if __name__ == "__main__":
    # Test connectivity
    response = c_request("get", "/accounts")  # Sandbox /accounts endpoint
