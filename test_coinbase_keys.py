import os
import time
import jwt
import requests

# Load keys from environment
ISS = os.getenv("COINBASE_ISS")
PEM = os.getenv("COINBASE_PEM_CONTENT")
BASE_URL = "https://api.coinbase.com"

if not ISS or not PEM:
    print("❌ Missing ISS or PEM content in environment variables")
    exit()

# Create JWT for authentication
timestamp = int(time.time())
payload = {
    "iss": ISS,
    "iat": timestamp,
    "exp": timestamp + 300
}

try:
    token = jwt.encode(payload, PEM, algorithm="ES256")
except Exception as e:
    print("❌ JWT encode failed:", e)
    exit()

headers = {
    "Authorization": f"Bearer {token}"
}

# Test /accounts endpoint
try:
    r = requests.get(f"{BASE_URL}/v2/accounts", headers=headers)
    print("Status Code:", r.status_code)
    print("Response:", r.text)
except Exception as e:
    print("❌ Request failed:", e)
