# app/nija_client.py

import os
import time
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -----------------------------
# Setup logger
# -----------------------------
logger.remove()
logger.add(lambda m: print(m, end=""), level=os.environ.get("LOG_LEVEL", "INFO"))

# -----------------------------
# Load Coinbase PEM and generate JWT
# -----------------------------
try:
    with open(os.environ["COINBASE_PEM_PATH"], "rb") as pem_file:
        pem_data = pem_file.read()
except KeyError:
    logger.error("COINBASE_PEM_PATH environment variable not set.")
    raise
except FileNotFoundError:
    logger.error(f"PEM file not found at path: {os.environ['COINBASE_PEM_PATH']}")
    raise

try:
    private_key = serialization.load_pem_private_key(
        pem_data,
        password=None,
        backend=default_backend()
    )
except Exception as e:
    logger.error(f"Failed to load PEM key: {e}")
    raise

# JWT payload
iat = int(time.time())
payload = {
    "sub": os.environ["COINBASE_ORG_ID"],  # Must be Org ID
    "iat": iat,
    "exp": iat + 300  # 5 minutes
}

try:
    COINBASE_JWT = jwt.encode(payload, private_key, algorithm="ES256")
    logger.info(f"Generated Coinbase JWT: {COINBASE_JWT[:50]}...")
except Exception as e:
    logger.error(f"Failed to generate JWT: {e}")
    raise

# -----------------------------
# Helper function for requests
# -----------------------------
def coinbase_request(method, endpoint, data=None):
    url = f"https://api.coinbase.com{endpoint}"
    headers = {
        "Authorization": f"Bearer {COINBASE_JWT}",
        "CB-VERSION": "2025-01-01",
        "Content-Type": "application/json"
    }
    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers)
        elif method.upper() == "POST":
            response = requests.post(url, json=data, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
        if response.status_code == 401:
            logger.error("Unauthorized: Check JWT, Org ID, and PEM key.")
        return response
    except Exception as e:
        logger.error(f"Request failed: {e}")
        raise

# -----------------------------
# Example usage
# -----------------------------
if __name__ == "__main__":
    resp = coinbase_request("GET", "/v2/accounts")
    try:
        logger.info(resp.json())
    except Exception as e:
        logger.error(f"Failed to parse response JSON: {e}")
