import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -------------------------
# Load environment variables
# -------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
COINBASE_API_SUB = os.getenv("COINBASE_API_SUB")  # full path: organizations/.../apiKeys/...
COINBASE_API_KID = os.getenv("COINBASE_API_KID")  # optional, can be same as SUB

if not COINBASE_ORG_ID or not COINBASE_API_SUB:
    raise SystemExit("❌ Missing required environment variables: COINBASE_ORG_ID or COINBASE_API_SUB")

# -------------------------
# Load PEM key
# -------------------------
if COINBASE_PEM_CONTENT:
    pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").strip().strip('"').strip("'")
elif COINBASE_PEM_PATH:
    with open(COINBASE_PEM_PATH, "r", encoding="utf-8") as f:
        pem_text = f.read()
else:
    raise SystemExit("❌ No PEM provided. Set COINBASE_PEM_CONTENT or COINBASE_PEM_PATH in env.")

try:
    private_key = serialization.load_pem_private_key(
        pem_text.encode(), password=None, backend=default_backend()
    )
    print("✅ PEM loaded successfully")
except Exception as e:
    raise SystemExit(f"❌ Failed to load PEM: {e}")

# -------------------------
# JWT sub & kid
# -------------------------
sub = COINBASE_API_SUB  # must be full path: organizations/.../apiKeys/...
kid = COINBASE_API_KID or sub

print("JWT sub (full path):", sub)
print("JWT kid:", kid)

# -------------------------
# Build JWT
# -------------------------
path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 120,
    "sub": sub,
    "request_path": path,
    "method": "GET"
}
headers = {"alg": "ES256", "kid": kid}

token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
print("JWT preview (first 80 chars):", token[:80])

# -------------------------
# Test Coinbase API call
# -------------------------
url = f"https://api.coinbase.com{path}"
response = requests.get(url, headers={"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-12"})
print("HTTP Status:", response.status_code)
print(response.text)

if response.status_code == 401:
    print("⚠️ 401 Unauthorized")
    print("- Check API Key matches Org ID")
    print("- Check API Key has 'view accounts' permission")
    print("- Check container/server clock is correct")
    raise SystemExit("❌ Cannot fetch Coinbase accounts")

print("✅ Successfully fetched Coinbase accounts!")

# -------------------------
# Continue with NijaBot trading logic here
# -------------------------
