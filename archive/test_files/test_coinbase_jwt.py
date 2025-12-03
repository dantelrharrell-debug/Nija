# test_coinbase_jwt.py
import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import datetime

# ----------------------------
# Load env vars
# ----------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")           
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")        # full path or ID
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT") 

if not COINBASE_ORG_ID or not COINBASE_API_KEY or not COINBASE_PEM_CONTENT:
    raise SystemExit("Missing required env vars")

# ----------------------------
# Extract API key ID
# ----------------------------
API_KEY_ID = COINBASE_API_KEY.split('/')[-1]

# ----------------------------
# Load PEM
# ----------------------------
pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").strip()
try:
    private_key = serialization.load_pem_private_key(
        pem_text.encode(), password=None, backend=default_backend()
    )
    print("✅ PEM loaded successfully")
except Exception as e:
    raise SystemExit(f"❌ Failed to load PEM: {e}")

# ----------------------------
# Check container time
# ----------------------------
print("Container UTC time:", datetime.datetime.utcnow().isoformat())

# ----------------------------
# Generate JWT
# ----------------------------
iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 300,  # 5 min validity
    "sub": API_KEY_ID,
    "request_path": f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts",
    "method": "GET"
}
headers_jwt = {"alg": "ES256", "kid": COINBASE_API_KEY}

token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
print("✅ JWT generated successfully")
print("JWT payload:", payload)

# ----------------------------
# Call Coinbase
# ----------------------------
url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
headers = {
    "Authorization": f"Bearer {token}",
    "CB-VERSION": "2025-11-16",
    "Content-Type": "application/json"
}

try:
    resp = requests.get(url, headers=headers)
    print("HTTP status:", resp.status_code)
    print("Response:", resp.text)
except Exception as e:
    print(f"❌ Request error: {e}")
