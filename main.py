import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -------------------------
# Environment variables (your keys directly)
# -------------------------
COINBASE_ORG_ID = "ce77e4ea-ecca-42ec-912a-b6b4455ab9d0"
COINBASE_API_SUB = "organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/9e33d60c-c9d7-4318-a2d5-24e1e53d2206"
COINBASE_API_KID = COINBASE_API_SUB  # using same path for kid
COINBASE_PEM_CONTENT = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEI...YOUR FULL PEM HERE...oUoQ==
-----END EC PRIVATE KEY-----"""

# -------------------------
# Load PEM key
# -------------------------
pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n").strip()
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
sub = COINBASE_API_SUB
kid = COINBASE_API_KID
print("JWT sub (full path):", sub)
print("JWT kid:", kid)

# -------------------------
# Function to fetch accounts with retry
# -------------------------
def fetch_accounts(retries=3):
    for attempt in range(1, retries + 1):
        iat = int(time.time())
        path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
        payload = {
            "iat": iat,
            "exp": iat + 120,
            "sub": sub,
            "request_path": path,
            "method": "GET"
        }
        headers_jwt = {"alg": "ES256", "kid": kid}
        token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers_jwt)

        url = f"https://api.coinbase.com{path}"
        response = requests.get(url, headers={"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-12"})

        print(f"Attempt {attempt} | HTTP Status: {response.status_code}")
        if response.status_code == 200:
            print("✅ Successfully fetched Coinbase accounts!")
            print(response.json())
            return response.json()
        elif response.status_code == 401:
            print("⚠️ 401 Unauthorized - retrying in 2 seconds")
            time.sleep(2)
        else:
            print(response.text)
            break
    raise SystemExit("❌ Cannot fetch Coinbase accounts after retries")

# -------------------------
# Run NijaBot fetch
# -------------------------
accounts = fetch_accounts()

# -------------------------
# Continue with your trading bot logic here
# -------------------------
print("💹 NijaBot ready to trade.")
