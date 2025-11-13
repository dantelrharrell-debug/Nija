# debug_coinbase_jwt.py
import os
import requests
import time
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

load_dotenv()

# --- Load credentials ---
API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
PEM = os.getenv("COINBASE_PEM")
ORG_ID = os.getenv("COINBASE_ORG_ID")
BASE_URL = "https://api.coinbase.com/api/v3/brokerage"

if not API_KEY_ID or not PEM or not ORG_ID:
    raise RuntimeError("Missing Coinbase Advanced API credentials!")

# --- Load private key ---
private_key = serialization.load_pem_private_key(
    PEM.encode(), password=None, backend=default_backend()
)

# --- Generate JWT ---
def generate_jwt(method="GET", path="/"):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 300,  # valid for 5 min
        "sub": API_KEY_ID,  # ONLY the API key UUID
        "request_path": path,
        "method": method.upper()
    }
    token = jwt.encode(payload, private_key, algorithm="ES256")
    return token, payload

# --- Test request ---
def test_accounts():
    path = f"/organizations/{ORG_ID}/accounts"
    token, payload = generate_jwt("GET", path)

    print("JWT payload (decoded for debug):", payload)
    print("JWT token (first 100 chars):", token[:100], "...")

    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": "2025-11-12"
    }

    response = requests.get(BASE_URL + path, headers=headers)
    print("HTTP status:", response.status_code)
    if response.status_code == 200:
        print("✅ Accounts fetched successfully!")
        print(response.json())
    else:
        print("❌ Failed to fetch accounts!")
        print(response.text)

if __name__ == "__main__":
    test_accounts()
