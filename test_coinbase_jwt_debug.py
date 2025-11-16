# test_coinbase_jwt_debug.py
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
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")           # org UUID
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")   # short UUID
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")         # full path
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT") # PEM block

# ✅ Env variable verification
print("✅ Verifying env variables:")
print("COINBASE_ORG_ID:", COINBASE_ORG_ID)
print("COINBASE_API_KEY_ID (short UUID):", COINBASE_API_KEY_ID)
print("COINBASE_API_SUB (full path):", COINBASE_API_SUB)
print("COINBASE_PEM_CONTENT length:", len(COINBASE_PEM_CONTENT or ""))

if not COINBASE_ORG_ID or not COINBASE_API_KEY_ID or not COINBASE_API_SUB or not COINBASE_PEM_CONTENT:
    raise SystemExit("❌ Missing required env vars: COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_API_SUB, COINBASE_PEM_CONTENT")

# ----------------------------
# Load PEM
# ----------------------------
pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").strip()
try:
    private_key = serialization.load_pem_private_key(
        pem_text.encode(),
        password=None,
        backend=default_backend()
    )
    print("✅ PEM loaded successfully")
except Exception as e:
    raise SystemExit(f"❌ Failed to load PEM: {e}")

# ----------------------------
# Check container UTC
# ----------------------------
print("Container UTC time:", datetime.datetime.utcnow().isoformat())

# ----------------------------
# Verify kid/sub match
# ----------------------------
if not COINBASE_API_SUB.endswith(COINBASE_API_KEY_ID):
    raise SystemExit("❌ COINBASE_API_SUB (kid) does not end with COINBASE_API_KEY_ID (sub).")

# ----------------------------
# Generate JWT for /accounts
# ----------------------------
iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 120,  # 2-minute validity
    "sub": COINBASE_API_KEY_ID,  # short UUID
    "request_path": f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts",
    "method": "GET"
}
headers_jwt = {"alg": "ES256", "kid": COINBASE_API_SUB}  # full path

token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)

# ----------------------------
# Print JWT debug info
# ----------------------------
print("✅ JWT generated successfully")
print("JWT headers:", headers_jwt)
print("JWT payload:", payload)
print("JWT token preview (first 50 chars):", token[:50], "...")

# ----------------------------
# Make request
# ----------------------------
url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
try:
    resp = requests.get(url, headers={
        "Authorization": f"Bearer {token}",
        "CB-VERSION": "2025-11-16",
        "Content-Type": "application/json"
    })
    print("HTTP status:", resp.status_code)
    print("Response:", resp.text)
except Exception as e:
    print(f"❌ Request error: {e}")
