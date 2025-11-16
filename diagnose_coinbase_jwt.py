import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# ----------------------------
# Load env vars
# ----------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")   # short UUID
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")         # full path
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

# Quick sanity check
if not all([COINBASE_ORG_ID, COINBASE_API_KEY_ID, COINBASE_API_SUB, COINBASE_PEM_CONTENT]):
    raise SystemExit("❌ Missing one or more environment variables.")

print("🔹 Environment vars loaded:")
print("ORG_ID:", COINBASE_ORG_ID)
print("API_KEY_ID (sub):", COINBASE_API_KEY_ID)
print("API_KEY_SUB (kid full path):", COINBASE_API_SUB[:30] + "..." if COINBASE_API_SUB else None)

# ----------------------------
# Load PEM
# ----------------------------
try:
    pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").strip()
    private_key = serialization.load_pem_private_key(
        pem_text.encode(), password=None, backend=default_backend()
    )
    print("✅ PEM loaded successfully")
except Exception as e:
    raise SystemExit(f"❌ Failed to load PEM: {e}")

# ----------------------------
# Generate JWT
# ----------------------------
iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 120,
    "sub": COINBASE_API_KEY_ID,
    "request_path": f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts",
    "method": "GET"
}
headers_jwt = {"alg": "ES256", "kid": COINBASE_API_SUB}

try:
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)
    print("✅ JWT generated successfully")
    print("JWT payload:", payload)
    print("JWT headers:", headers_jwt)
except Exception as e:
    raise SystemExit(f"❌ Failed to generate JWT: {e}")

# ----------------------------
# Test request
# ----------------------------
url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
try:
    resp = requests.get(url, headers={
        "Authorization": f"Bearer {token}",
        "CB-VERSION": "2025-11-16"
    })
    print("HTTP status:", resp.status_code)
    if resp.status_code == 401:
        print("⚠️ 401 Unauthorized — check the following:")
        print("  - Is 'sub' the short UUID of the key?")
        print("  - Is 'kid' the full API key path ending with the short UUID?")
        print("  - Does the key have 'accounts:read' permission?")
    print("Response text:", resp.text)
except Exception as e:
    print(f"❌ Request failed: {e}")
