import os
import jwt
import time
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Load your environment variables
ORG_ID = os.environ.get("COINBASE_ORG_ID")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT")
API_KEY = os.environ.get("COINBASE_API_KEY")  # optional, not used for JWT

if not ORG_ID or not PEM_RAW:
    raise ValueError("Missing COINBASE_ORG_ID or COINBASE_PEM_CONTENT")

# Fix PEM formatting if necessary
pem = PEM_RAW.replace("\\n", "\n").encode("utf-8")

# Load EC private key
private_key = serialization.load_pem_private_key(pem, password=None, backend=default_backend())

# JWT claims
iat = int(time.time())
exp = iat + 300  # 5 minutes
claims = {
    "sub": ORG_ID,
    "iat": iat,
    "exp": exp,
    "kid": ORG_ID,  # Coinbase sometimes expects 'kid' = org_id
}

# JWT header
headers = {
    "alg": "ES256",
    "typ": "JWT",
    "kid": ORG_ID
}

# Encode JWT
token = jwt.encode(claims, private_key, algorithm="ES256", headers=headers)

print("=== JWT DEBUG ===")
print("Org ID:", ORG_ID)
print("JWT length:", len(token))
print("JWT preview:", token[:80], "...")
print("Full JWT:", token)
