import time
import requests
import jwt  # PyJWT
from cryptography.hazmat.primitives import serialization

# -------------------------------
# CONFIGURATION (replace these)
# -------------------------------
API_KEY = "YOUR_API_KEY_ID"          # Coinbase API key ID
ORG_ID = "YOUR_ORG_ID"               # Coinbase Organization ID
PEM_PATH = "path/to/your_key.pem"   # Path to your private key PEM file

# -------------------------------
# Load PEM private key
# -------------------------------
with open(PEM_PATH, "rb") as f:
    private_key_data = f.read()

private_key = serialization.load_pem_private_key(
    private_key_data,
    password=None
)

print("✅ PEM loaded successfully.")

# -------------------------------
# Generate JWT
# -------------------------------
payload = {
    "sub": API_KEY,
    "iat": int(time.time()),
    "exp": int(time.time()) + 300  # 5 minutes expiry
}

token = jwt.encode(
    payload,
    private_key,
    algorithm="ES256"
)

print("✅ JWT generated successfully.")

# -------------------------------
# Test /accounts endpoint
# -------------------------------
url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{ORG_ID}/accounts"
headers = {
    "Authorization": f"Bearer {token}",
    "CB-VERSION": "2025-11-15"  # latest version date
}

response = requests.get(url, headers=headers)

print(f"HTTP Status Code: {response.status_code}")
print("Response:")
print(response.text)
