import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# ------------------------------
# CONFIG - Replace with your values
# ------------------------------
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")       # API Key ID
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")       # Organization ID
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # Raw PEM string
API_URL = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"

# ------------------------------
# Load private key
# ------------------------------
try:
    private_key = serialization.load_pem_private_key(
        COINBASE_PEM_CONTENT.encode(),
        password=None,
        backend=default_backend()
    )
    print("✅ PEM private key loaded successfully")
except Exception as e:
    print("❌ Failed to load PEM key:", e)
    exit(1)

# ------------------------------
# Generate JWT
# ------------------------------
def generate_jwt():
    payload = {
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,  # 5 minutes max
        "sub": COINBASE_API_KEY
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")
    return token

jwt_token = generate_jwt()
print("✅ JWT generated")

# ------------------------------
# Test fetching accounts
# ------------------------------
headers = {
    "Authorization": f"Bearer {jwt_token}",
    "CB-VERSION": "2025-11-15"
}

try:
    response = requests.get(API_URL, headers=headers)
    if response.status_code == 200:
        print("✅ Accounts fetched successfully:")
        print(response.json())
    else:
        print(f"❌ HTTP {response.status_code}: {response.text}")
except Exception as e:
    print("❌ Request failed:", e)
