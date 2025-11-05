import os
import time
import jwt
import requests

# Load your keys from environment
API_KEY = os.getenv("organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5")
API_SECRET = os.getenv("nMHcCAQEEIC4EDrIQiByWHS5qIrHsMI6SZb0sYSqx744G2kvqr+PCoAoGCCqGSM49\nAwEHoUQDQgAE3gkuCL8xUOM81/alCSOLqEtyUmY7A09z7QEAoN/cfCtbAslo6pXR\nqONKAu6GS9PS/W3BTFyB6ZJBRzxMZeNzBg")
PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")

if not all([API_KEY, API_SECRET]):
    raise SystemExit("❌ Missing API key or secret")

# Coinbase Advanced JWT payload
timestamp = int(time.time())
payload = {
    "iat": timestamp,
    "exp": timestamp + 300,  # token valid 5 minutes
    "sub": API_KEY,
}

token = jwt.encode(payload, API_SECRET, algorithm="HS256")

headers = {
    "CB-ACCESS-KEY": API_KEY,
    "CB-ACCESS-SIGN": token,
    "CB-ACCESS-PASSPHRASE": PASSPHRASE,
    "Content-Type": "application/json",
}

# Test endpoint: get accounts
url = "https://api.coinbase.com/v2/accounts"

response = requests.get(url, headers=headers)

print("Status code:", response.status_code)
print("Response:", response.text)
