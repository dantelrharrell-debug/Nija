import os
import time
import jwt  # PyJWT library
from cryptography.hazmat.primitives import serialization

# ----------------------------
# Load secrets from env
# ----------------------------
API_KEY = os.getenv("COINBASE_API_KEY")
ORG_ID = os.getenv("COINBASE_ORG_ID")
PEM_PATH = os.getenv("COINBASE_PEM_PATH")

print("Testing Coinbase credentials...")
print(f"API_KEY: {API_KEY}")
print(f"ORG_ID: {ORG_ID}")
print(f"PEM_PATH: {PEM_PATH}")

# ----------------------------
# Load PEM
# ----------------------------
try:
    with open(PEM_PATH, "rb") as f:
        private_key_data = f.read()
    private_key = serialization.load_pem_private_key(private_key_data, password=None)
    print("✅ PEM loaded successfully")
except Exception as e:
    print("❌ Failed to load PEM:", e)
    exit(1)

# ----------------------------
# Generate JWT
# ----------------------------
try:
    payload = {
        "sub": API_KEY,
        "iat": int(time.time()),
        "exp": int(time.time()) + 300  # 5 minutes
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")
    print("✅ JWT generated successfully:")
    print(token)
except Exception as e:
    print("❌ Failed to generate JWT:", e)
    exit(1)

# ----------------------------
# Optional: Test API call
# ----------------------------
import requests

url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{ORG_ID}/accounts"
headers = {
    "Authorization": f"Bearer {token}",
    "CB-VERSION": "2025-11-15"
}

resp = requests.get(url, headers=headers)
print("HTTP status code:", resp.status_code)
print("Response body:", resp.text)
