import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- Load environment variables ---
API_KEY_ID = os.environ.get("COINBASE_API_KEY")  # your API key ID
PEM = os.environ.get("COINBASE_PEM", "").replace("\\n", "\n")  # private key
ORG_ID = os.environ.get("COINBASE_ORG_ID")  # organization ID

if not API_KEY_ID or not PEM or not ORG_ID:
    raise Exception("Missing COINBASE_API_KEY, COINBASE_PEM, or COINBASE_ORG_ID")

# --- Load private key ---
private_key = serialization.load_pem_private_key(
    PEM.encode(), password=None, backend=default_backend()
)

# --- Request details ---
path = f"/api/v3/brokerage/organizations/{ORG_ID}/accounts"
url = f"https://api.coinbase.com{path}"

iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 120,  # JWT valid for 2 minutes
    "sub": API_KEY_ID,
    "request_path": path,
    "method": "GET"
}

headers = {
    "alg": "ES256",
    "kid": API_KEY_ID
}

# --- Generate JWT ---
token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)

# --- Debug output ---
print("JWT Token preview:", token[:50] + "...")
print("JWT Header:", jwt.get_unverified_header(token))
print("JWT Payload:", jwt.decode(token, options={"verify_signature": False}))
print("Request URL:", url)

# --- Make request ---
response = requests.get(url, headers={
    "Authorization": f"Bearer {token}",
    "CB-VERSION": "2025-11-12"
})

print("HTTP Status Code:", response.status_code)
print("Response:", response.text)
