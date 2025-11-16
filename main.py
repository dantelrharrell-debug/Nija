import os
import time
import requests
import jwt  # PyJWT
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# -------------------------
# Load environment variables
# -------------------------
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")  # Full path
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

if not all([COINBASE_ORG_ID, COINBASE_API_KEY, COINBASE_PEM_CONTENT]):
    raise ValueError("Missing required environment variables")

# -------------------------
# Load PEM private key
# -------------------------
try:
    private_key = serialization.load_pem_private_key(
        COINBASE_PEM_CONTENT.encode(),
        password=None,
        backend=default_backend()
    )
    print("✅ PEM private key loaded successfully")
except Exception as e:
    print(f"❌ Failed to load PEM key: {e}")
    raise e

# -------------------------
# Generate JWT with kid
# -------------------------
payload = {
    "iat": int(time.time()),
    "exp": int(time.time()) + 300,  # 5 minutes
    "sub": COINBASE_API_KEY.split('/')[-1]  # key ID
}

headers = {
    "kid": COINBASE_API_KEY  # full API key path required by Coinbase
}

try:
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    print("✅ JWT generated successfully")
    print("JWT preview (first 50 chars):", token[:50])
except Exception as e:
    print(f"❌ Failed to generate JWT: {e}")
    raise e

# -------------------------
# Test fetch accounts
# -------------------------
url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
headers = {"Authorization": f"Bearer {token}"}

try:
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        print("✅ Accounts fetched successfully!")
        print(response.json())
    else:
        print(f"❌ Failed to fetch accounts. Status: {response.status_code}")
        print(response.text)
except Exception as e:
    print(f"❌ Error fetching accounts: {e}")
