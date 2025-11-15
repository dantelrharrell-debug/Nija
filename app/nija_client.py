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

# Basic console logging
logger.remove()
logger.add(lambda msg: print(msg, end=""), level="INFO")

# -----------------------
# Environment variables
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")  # PEM string

# Load PEM private key
private_key = serialization.load_pem_private_key(
    COINBASE_PEM_CONTENT.encode(),
    password=None,
    backend=default_backend()
)

# -----------------------
# Function to generate JWT
def generate_jwt():
    iat = int(time.time())
    exp = iat + 300  # 5 minutes expiration
    payload = {
        "sub": COINBASE_API_KEY,
        "iat": iat,
        "exp": exp
    }
    headers = {
        "kid": os.environ.get("COINBASE_JWT_KID")  # Your key ID
    }
    token = jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers=headers
    )
    return token

# -----------------------
# Function to verify JWT structure
def verify_jwt_struct(token):
    header_b64, payload_b64, _ = token.split(".")
    header = json.loads(base64.urlsafe_b64decode(header_b64 + "=="))
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    return header, payload

# -----------------------
# Generate JWT and log info
token = generate_jwt()
header, payload = verify_jwt_struct(token)
logger.info("JWT header.kid: " + str(header.get("kid")))
logger.info("JWT payload.sub: " + str(payload.get("sub")))
logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())

# -----------------------
# Example Coinbase request using JWT
def coinbase_get(path):
    url = f"https://api.coinbase.com/v2{path}"
    headers = {
        "Authorization": f"Bearer {token}"
    }
    resp = requests.get(url, headers=headers)
    logger.info(f"Coinbase response status: {resp.status_code}")
    logger.info(f"Response body: {resp.text}")
    return resp

# Test request (optional)
# coinbase_get("/accounts")
