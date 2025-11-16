import os
import time
import requests
import jwt  # PyJWT library
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# 🌟 Load environment variables
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")  # Full path or just ID
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")  # Make sure \n are preserved

# Extract API_KEY_ID if COINBASE_API_KEY is full path
API_KEY_ID = COINBASE_API_KEY.split('/')[-1]

# 🌟 Load PEM private key
try:
    private_key = serialization.load_pem_private_key(
        COINBASE_PEM_CONTENT.encode(),
        password=None,
        backend=default_backend()
    )
    print("✅ PEM private key loaded successfully")
except Exception as e:
    print("❌ Failed to load PEM key:", e)
    raise e

# 🌟 Generate JWT
payload = {
    "iat": int(time.time()),
    "exp": int(time.time()) + 300,  # 5 minutes expiration
    "sub": API_KEY_ID
}

try:
    token = jwt.encode(payload, private_key, algorithm="ES256")
    print("✅ JWT generated successfully")
    print("JWT preview (first 50 chars):", token[:50])
except Exception as e:
    print("❌ Failed to generate JWT:", e)
    raise e

# 🌟 Test: Fetch Coinbase accounts
url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
headers = {
    "Authorization": f"Bearer {token}"
}

try:
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        print("✅ Accounts fetched successfully!")
        print(response.json())
    else:
        print(f"❌ Failed to fetch accounts. Status: {response.status_code}")
        print(response.text)
except Exception as e:
    print("❌ Error fetching accounts:", e)
