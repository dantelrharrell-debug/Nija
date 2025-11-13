import os
import time
import requests
import jwt
from loguru import logger
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Load Coinbase credentials from environment variables
API_KEY_ID = os.environ.get("COINBASE_API_KEY")
PEM_CONTENT = os.environ.get("COINBASE_PEM", "").replace("\\n", "\n")

if not API_KEY_ID:
    logger.error("COINBASE_API_KEY not set!")
if not PEM_CONTENT:
    logger.error("COINBASE_PEM not set or empty!")

try:
    private_key = serialization.load_pem_private_key(
        PEM_CONTENT.encode(), password=None, backend=default_backend()
    )
    logger.info("Private key loaded successfully")
except Exception as e:
    logger.exception("Failed to load private key: %s", e)
    raise

def generate_jwt(method: str, request_path: str) -> str:
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,           # expires in 2 minutes
        "sub": API_KEY_ID,           # must be API key ID
        "request_path": request_path,
        "method": method.upper()
    }
    headers = {
        "alg": "ES256",
        "kid": API_KEY_ID
    }
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)

    # Debug header/payload
    import base64
    header_b64, payload_b64, _ = token.split(".")
    logger.info("DEBUG_JWT: token_preview=%s", token[:200])
    logger.info("DEBUG_JWT: header=%s", base64.urlsafe_b64decode(header_b64 + "==").decode())
    logger.info("DEBUG_JWT: payload=%s", base64.urlsafe_b64decode(payload_b64 + "==").decode())

    return token

def test_accounts():
    org_id = os.environ.get("COINBASE_ORG_ID")  # make sure this is set
    path = f"/api/v3/brokerage/organizations/{org_id}/accounts"
    url = f"https://api.coinbase.com{path}"
    token = generate_jwt("GET", path)

    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": "2025-11-12"
    }

    resp = requests.get(url, headers=headers)
    logger.info("HTTP status code: %s", resp.status_code)
    logger.info("Response text: %s", resp.text[:500])

    if resp.status_code != 200:
        logger.error("Failed to fetch accounts. HTTP %s: %s", resp.status_code, resp.text)
    else:
        logger.info("Accounts fetched successfully: %s", resp.json())

if __name__ == "__main__":
    test_accounts()
