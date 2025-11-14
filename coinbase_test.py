import os
import time
import jwt
import requests

# -------------------------------
# Load from environment (or replace with your values)
# -------------------------------
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")

# -------------------------------
# Prepare JWT
# -------------------------------
iat = int(time.time())
exp = iat + 30  # 30-second validity

payload = {
    "iat": iat,
    "exp": exp,
    "sub": COINBASE_API_KEY,
}

try:
    jwt_token = jwt.encode(
        payload,
        COINBASE_PEM_CONTENT,
        algorithm="ES256",
    )
    print("✅ JWT generated successfully:")
    print(jwt_token[:50] + "...")  # preview first 50 chars
except Exception as e:
    print("❌ JWT generation failed:", e)
    exit(1)

# -------------------------------
# Test API call (safe endpoint)
# -------------------------------
url = "https://api.coinbase.com/v2/accounts"  # read-only endpoint
headers = {
    "Authorization": f"Bearer {jwt_token}",
    "CB-ACCESS-PASSPHRASE": COINBASE_API_PASSPHRASE,
}

response = requests.get(url, headers=headers)
print("\n--- Coinbase Response ---")
print("Status Code:", response.status_code)
print("Response Body:", response.text[:500])  # first 500 chars
