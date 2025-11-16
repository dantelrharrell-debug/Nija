import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# 🔹 Load your env variables
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")  # full path or ID
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

# 🔹 Extract only API key ID if full path is provided
API_KEY_ID = COINBASE_API_KEY.split('/')[-1]

# 🔹 Convert literal \n to real newlines
pem_corrected = COINBASE_PEM_CONTENT.replace("\\n", "\n")

# 🔹 Load private key safely
try:
    private_key = serialization.load_pem_private_key(
        pem_corrected.encode(),
        password=None,
        backend=default_backend()
    )
    print("✅ PEM private key loaded successfully")
except Exception as e:
    print(f"❌ Failed to load PEM key: {e}")
    raise e

# 🔹 Generate JWT
payload = {
    "iat": int(time.time()),
    "exp": int(time.time()) + 300,  # 5 minutes validity
    "sub": API_KEY_ID
}

try:
    token = jwt.encode(payload, private_key, algorithm="ES256")
    print("✅ JWT generated successfully")
    print("JWT preview (first 50 chars):", token[:50])
except Exception as e:
    print(f"❌ Failed to generate JWT: {e}")
    raise e

# 🔹 Test fetching accounts
url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
headers = {"Authorization": f"Bearer {token}"}

try:
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        print("✅ Accounts fetched successfully!")
        print(response.json())
    else:
        print(f"⚠️ Failed to fetch accounts. Status: {response.status_code}")
        print(response.text)
except Exception as e:
    print(f"❌ Request error: {e}")
