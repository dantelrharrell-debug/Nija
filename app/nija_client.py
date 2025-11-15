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
logger.add(lambda msg: print(msg, end=""), level="INFO")

# -----------------------
# Environment variables
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")  # PEM string
COINBASE_JWT_KID = os.environ.get("COINBASE_JWT_KID")  # UUID

# -----------------------
# Load PEM private key safely
def load_private_key(pem_str):
    return serialization.load_pem_private_key(
        pem_str.encode(),
        password=None,
        backend=default_backend()
    )

private_key = load_private_key(COINBASE_PEM_CONTENT)

# -----------------------
# JWT management
current_token = None
token_expiry = 0

def generate_jwt():
    global token_expiry
    iat = int(time.time())
    exp = iat + 300  # 5 minutes
    payload = {
        "sub": COINBASE_API_KEY,
        "iat": iat,
        "exp": exp
    }
    headers = {
        "kid": COINBASE_JWT_KID
    }
    token = jwt.encode(
        payload,
        private_key,
        algorithm="ES256",
        headers=headers
    )
    token_expiry = exp
    return token

def get_jwt():
    global current_token, token_expiry
    if current_token is None or time.time() > token_expiry - 10:
        current_token = generate_jwt()
        logger.info(f"Generated new JWT, expires at {datetime.datetime.utcfromtimestamp(token_expiry)} UTC")
        # Log JWT structure
        header, payload = verify_jwt_struct(current_token)
        logger.info("JWT header.kid: " + str(header.get("kid")))
        logger.info("JWT payload.sub: " + str(payload.get("sub")))
        logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())
    return current_token

# -----------------------
# JWT structure verification
def verify_jwt_struct(token):
    header_b64, payload_b64, _ = token.split(".")
    header = json.loads(base64.urlsafe_b64decode(header_b64 + "=="))
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    return header, payload

# -----------------------
# Coinbase API request wrapper
def coinbase_get(path):
    token = get_jwt()
    url = f"https://api.coinbase.com/v2{path}"
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)
    logger.info(f"Coinbase GET {path} status: {resp.status_code}")
    if resp.status_code != 200:
        logger.warning(f"Response: {resp.text}")
    return resp

# -----------------------
# Optional: auto-refresh loop for testing
if __name__ == "__main__":
    while True:
        coinbase_get("/accounts")  # test endpoint
        time.sleep(60)  # refresh every 60 seconds
