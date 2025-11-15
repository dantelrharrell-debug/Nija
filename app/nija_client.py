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
logger.add(lambda m: print(m, end=""), level="INFO")


# -----------------------
# JWT Generation
def create_jwt():
    """
    Generates a fresh ES256 JWT for Coinbase Advanced Trade API
    """
    API_KEY = os.getenv("COINBASE_API_KEY")      # "organizations/{org_id}/apiKeys/{key_id}"
    PRIVATE_PEM = os.getenv("COINBASE_PEM_CONTENT")
    KEY_ID = os.getenv("COINBASE_JWT_KID")       # Coinbase key id

    if not all([API_KEY, PRIVATE_PEM, KEY_ID]):
        logger.error("Missing one or more required environment variables: COINBASE_API_KEY, COINBASE_PEM_CONTENT, COINBASE_JWT_KID")
        return None

    private_key = serialization.load_pem_private_key(
        PRIVATE_PEM.encode("utf-8"),
        password=None,
        backend=default_backend()
    )

    now = int(time.time())
    payload = {
        "sub": API_KEY,
        "iat": now,
        "exp": now + 300  # expire in 5 minutes
    }

    headers = {
        "alg": "ES256",
        "kid": KEY_ID
    }

    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token


# -----------------------
# JWT Debugging
def verify_jwt_struct(token):
    """
    Decode JWT without verifying signature (debugging only)
    """
    header_b64, payload_b64, _ = token.split(".")
    header = json.loads(base64.urlsafe_b64decode(header_b64 + "=="))
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    return header, payload


# -----------------------
# Main Coinbase test function
def test_coinbase_connection():
    token = create_jwt()
    if not token:
        return

    # Log JWT details
    header, payload = verify_jwt_struct(token)
    logger.info("JWT header.kid: " + str(header.get("kid")))
    logger.info("JWT payload.sub: " + str(payload.get("sub")))
    logger.info("Server UTC time: " + datetime.datetime.utcnow().isoformat())
    logger.info("Generated JWT: " + token)

    # Test request to Coinbase
    url = "https://api.coinbase.com/api/v3/brokerage/accounts"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        logger.info("Coinbase status code: " + str(response.status_code))
        logger.info("Coinbase response: " + response.text[:500] + ("..." if len(response.text) > 500 else ""))
    except Exception as e:
        logger.error(f"Request failed: {e}")


# -----------------------
# Run test if executed directly
if __name__ == "__main__":
    test_coinbase_connection()
