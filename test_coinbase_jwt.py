# test_coinbase_jwt.py
import os
import time
import jwt
import requests

COINBASE_ISS = os.getenv("COINBASE_ISS")                 # API key id (uuid)
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT") # PEM private key (full content)
BASE_URL = os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")

def test_advanced():
    if not COINBASE_ISS or not COINBASE_PEM_CONTENT:
        print("❌ Missing COINBASE_ISS or COINBASE_PEM_CONTENT")
        return

    iat = int(time.time())
    payload = {"iss": COINBASE_ISS, "iat": iat, "exp": iat + 300}
    try:
        token = jwt.encode(payload, COINBASE_PEM_CONTENT, algorithm="ES256")
    except Exception as e:
        print("❌ JWT creation failed:", e)
        return

    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(f"{BASE_URL}/accounts", headers=headers, timeout=10)
        print("Status Code:", r.status_code)
        print("Response:", r.text)
    except Exception as e:
        print("❌ Request failed:", e)

if __name__ == "__main__":
    test_advanced()
