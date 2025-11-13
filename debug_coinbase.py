import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger

# --- Load environment variables ---
API_KEY_ID = os.environ.get("COINBASE_API_KEY")
PEM = os.environ.get("COINBASE_PEM", "").replace("\\n", "\n")
ORG_ID = os.environ.get("COINBASE_ORG_ID")

if not API_KEY_ID or not PEM or not ORG_ID:
    logger.error("Missing one or more required environment variables: COINBASE_API_KEY, COINBASE_PEM, COINBASE_ORG_ID")
    exit(1)

# --- Load private key ---
try:
    private_key = serialization.load_pem_private_key(
        PEM.encode(), password=None, backend=default_backend()
    )
    logger.info("Private key loaded successfully")
except Exception as e:
    logger.exception("Failed to load private key: %s", e)
    exit(1)

# --- Build request ---
path = f"/api/v3/brokerage/organizations/{ORG_ID}/accounts"
url = f"https://api.coinbase.com{path}"

iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 120,        # 2 minutes expiry
    "sub": API_KEY_ID,       # API key ID
    "request_path": path,    # must exactly match
    "method": "GET"
}

headers = {
    "alg": "ES256",
    "kid": API_KEY_ID
}

# --- Generate JWT ---
try:
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
except Exception as e:
    logger.exception("Failed to generate JWT: %s", e)
    exit(1)

# --- Debug output ---
print("\n--- JWT DEBUG INFO ---")
print("JWT Token:", token)
print("JWT Header:", jwt.get_unverified_header(token))
print("JWT Payload:", jwt.decode(token, options={"verify_signature": False}))
print("Request Path:", path)
print("Request URL:", url)
print("Local Timestamp:", iat)
print("--- END JWT DEBUG INFO ---\n")

# --- Make request ---
try:
    resp = requests.get(url, headers={
        "Authorization": f"Bearer {token}",
        "CB-VERSION": "2025-11-12"
    })
    print("HTTP Status Code:", resp.status_code)
    print("Response Text:", resp.text)
except requests.exceptions.HTTPError as http_err:
    logger.error("HTTP error occurred: %s", http_err)
except Exception as e:
    logger.exception("Request failed: %s", e)
