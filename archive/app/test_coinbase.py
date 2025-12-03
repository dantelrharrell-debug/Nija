import os
import time
import requests
import jwt  # PyJWT library
from cryptography.hazmat.primitives import serialization

# ===========================
# 1️⃣ Load environment variables
# ===========================
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")  # Full path: organizations/.../apiKeys/...
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # PEM private key with literal \n

# ===========================
# 2️⃣ Load PEM private key
# ===========================
private_key = serialization.load_pem_private_key(
    COINBASE_PEM_CONTENT.encode(),
    password=None
)

# ===========================
# 3️⃣ Build JWT payload
# ===========================
# Timestamp
iat = int(time.time())
exp = iat + 300  # 5 minutes

# Include `uri` in the payload per Coinbase docs
uri_path = f"GET /api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
payload = {
    "sub": COINBASE_API_KEY,  # Full API key path
    "iat": iat,
    "exp": exp,
    "uri": uri_path
}

# ===========================
# 4️⃣ Generate JWT
# ===========================
token = jwt.encode(payload, private_key, algorithm="ES256")
print("✅ JWT generated successfully")
print("JWT preview (first 50 chars):", token[:50])

# ===========================
# 5️⃣ Try fetching accounts
# ===========================
# Two paths: org-specific and generic
endpoints = [
    f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts",
    "https://api.coinbase.com/api/v3/brokerage/accounts"
]

headers = {"Authorization": f"Bearer {token}"}

for url in endpoints:
    print(f"\n➡️ Trying endpoint: {url}")
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        print("✅ Accounts fetched successfully!")
        print(response.json())
    else:
        print(f"❌ Failed to fetch accounts. Status: {response.status_code}")
        print(response.text)
