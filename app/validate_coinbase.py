# file: validate_coinbase.py

import os
import time
import jwt
import requests
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

logger.add(lambda msg: print(msg, end=''))

def load_env():
    org_id = os.environ.get("COINBASE_ORG_ID")
    api_key = os.environ.get("COINBASE_API_KEY")
    pem_content = os.environ.get("COINBASE_PEM_CONTENT")

    if not org_id or not api_key or not pem_content:
        logger.error("Missing one or more environment variables!")
        return None, None, None
    return org_id, api_key, pem_content

def generate_jwt(org_id, api_key, pem_raw):
    try:
        private_key = serialization.load_pem_private_key(
            pem_raw.encode(),
            password=None,
            backend=default_backend()
        )

        iat = int(time.time())
        exp = iat + 300  # 5 min expiration

        payload = {
            "sub": org_id,
            "iat": iat,
            "exp": exp,
            "kid": api_key
        }

        token = jwt.encode(
            payload,
            private_key,
            algorithm="ES256"
        )

        return token
    except Exception as e:
        logger.error(f"Failed to generate JWT: {e}")
        return None

def test_auth(jwt_token):
    url = "https://advanced-api.coinbase.com/v1/organizations"
    headers = {"Authorization": f"Bearer {jwt_token}"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            logger.success("✅ Coinbase Advanced API authentication SUCCESSFUL!")
        else:
            logger.error(f"❌ Authentication failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Request error: {e}")

if __name__ == "__main__":
    org_id, api_key, pem_content = load_env()
    if org_id and api_key and pem_content:
        token = generate_jwt(org_id, api_key, pem_content)
        if token:
            logger.info(f"Generated JWT preview (first 50 chars): {token[:50]}")
            test_auth(token)
