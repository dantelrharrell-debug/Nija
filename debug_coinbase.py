import os
import time
import jwt
import requests

# ---- CONFIG ----
COINBASE_ORG_ID = os.environ.get("COINBASE_ORG_ID")  # e.g., ce77e4ea-ecca-42ec-912a-b6b4455ab9d0
COINBASE_PEM = os.environ.get("COINBASE_PEM_CONTENT")  # full PEM including BEGIN/END lines
COINBASE_KEY_ID = os.environ.get("COINBASE_API_KEY")  # The 'kid' for JWT header

API_URL = f"https://api.coinbase.com/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"

# ---- GENERATE JWT ----
def generate_jwt():
    now = int(time.time())
    payload = {
        "iat": now,
        "exp": now + 300,  # 5 min expiry
        "sub": COINBASE_ORG_ID
    }
    headers = {"kid": COINBASE_KEY_ID}
    token = jwt.encode(payload, COINBASE_PEM, algorithm="ES256", headers=headers)
    return token

# ---- TEST REQUEST ----
def test_accounts():
    token = generate_jwt()
    print("Generated JWT (first 30 chars):", token[:30])

    headers = {
        "Authorization": f"Bearer {token}",
        "CB-VERSION": "2025-11-01"
    }

    resp = requests.get(API_URL, headers=headers)
    print("HTTP Status Code:", resp.status_code)
    print("Response Body:", resp.text)

if __name__ == "__main__":
    test_accounts()
