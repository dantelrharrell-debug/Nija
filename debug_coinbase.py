import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from loguru import logger

# --- Load credentials ---
API_KEY_ID = os.environ.get("COINBASE_API_KEY")
PEM = os.environ.get("COINBASE_PEM", "").replace("\\n", "\n")
ORG_ID = os.environ.get("COINBASE_ORG_ID")

if not API_KEY_ID or not PEM or not ORG_ID:
    logger.error("Missing environment variables: COINBASE_API_KEY, COINBASE_PEM, COINBASE_ORG_ID")
    exit(1)

# --- Load private key ---
try:
    private_key = serialization.load_pem_private_key(
        PEM.encode(),
        password=None,
        backend=default_backend()
    )
    logger.info("Private key loaded successfully")
except Exception as e:
    logger.exception("Failed to load private key: %s", e)
    exit(1)

# --- Request details ---
path = f"/api/v3/brokerage/organizations/{ORG_ID}/accounts"
url = f"https://api.coinbase.com{path}"

# --- Generate JWT ---
iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 120,              # token valid for 2 minutes per docs  [oai_citation:1‡Coinbase Developer Docs](https://docs.cdp.coinbase.com/get-started/authentication/overview?utm_source=chatgpt.com)
    "sub": API_KEY_ID,
    "request_path": path,
    "method": "GET"
}
headers = {
    "alg": "ES256",
    "kid": API_KEY_ID
}

try:
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
except Exception as e:
    logger.exception("Failed to generate JWT: %s", e)
    exit(1)

# --- Debug prints (helpful for diagnosing 401) ---
print("JWT:", token)
print("JWT Header:", jwt.get_unverified_header(token))
print("JWT Payload:", jwt.decode(token, options={"verify_signature": False}))
print("Request path:", path)
print("Request URL:", url)

# --- Make the API call ---
resp = requests.get(url, headers={
    "Authorization": f"Bearer {token}",
    "CB-VERSION": "2025-11-12"
})

print("HTTP status code:", resp.status_code)
print("Response body:", resp.text)
