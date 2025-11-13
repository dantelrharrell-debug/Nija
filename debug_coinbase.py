import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Load environment variables
API_KEY_ID = os.environ["COINBASE_API_KEY"]          # Must be key ID, not secret
PEM = os.environ["COINBASE_PEM"].replace("\\n","\n")
ORG_ID = os.environ["COINBASE_ORG_ID"]

# Load private key
private_key = serialization.load_pem_private_key(
    PEM.encode(),
    password=None,
    backend=default_backend()
)

# Correct request path for JWT (no /api/v3)
path = f"/brokerage/organizations/{ORG_ID}/accounts"
url = f"https://api.coinbase.com/api/v3{path}"

# Generate JWT
iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 120,       # expires in 2 minutes
    "sub": API_KEY_ID,      # must be API key ID
    "request_path": path,   # exact path Coinbase expects
    "method": "GET"
}
headers = {"alg":"ES256","kid":API_KEY_ID}

token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)

# Debug prints
print("JWT:", token)
print("JWT Header:", jwt.get_unverified_header(token))
print("JWT Payload:", jwt.decode(token, options={"verify_signature": False}))
print("Request path:", path)
print("Request URL:", url)

# Make the request
resp = requests.get(url, headers={
    "Authorization": f"Bearer {token}",
    "CB-VERSION": "2025-11-12"
})

print("HTTP status code:", resp.status_code)
print("Response text:", resp.text[:500])  # truncated for safety
