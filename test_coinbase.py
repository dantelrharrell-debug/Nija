import time
import jwt  # PyJWT library
import requests
from cryptography.hazmat.primitives import serialization

# --------------------------
# Your Coinbase credentials
# --------------------------
COINBASE_API_KEY = "your_api_key_here"      # API Key ID
COINBASE_ORG_ID = "ce77e4ea-ecca-42ec-912a-b6b4455ab9d0"
COINBASE_PEM_PATH = "/path/to/coinbase.pem"  # Local path or Railway secret path

# --------------------------
# Load PEM private key
# --------------------------
with open(COINBASE_PEM_PATH, "rb") as f:
    private_key = serialization.load_pem_private_key(
        f.read(),
        password=None
    )

# --------------------------
# Create JWT
# --------------------------
iat = int(time.time())
exp = iat + 300  # expires in 5 minutes
payload = {
    "iat": iat,
    "exp": exp,
    "sub": COINBASE_API_KEY
}

jwt_token = jwt.encode(payload, private_key, algorithm="ES256")
print("Generated JWT:", jwt_token)

# --------------------------
# Test Coinbase accounts endpoint
# --------------------------
url = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
headers = {
    "Authorization": f"Bearer {jwt_token}",
    "CB-VERSION": "2025-11-15"
}

response = requests.get(url, headers=headers)
print("HTTP Status:", response.status_code)
print("Response:", response.text)
