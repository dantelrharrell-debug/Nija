# test_advanced_coinbase.py
import os
import time
import jwt
import requests

# Configure
BASE = os.getenv("COINBASE_ADVANCED_BASE", "https://api.cdp.coinbase.com")
COINBASE_ISS = os.getenv("COINBASE_ISS")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT", "").replace("\\n", "\n")

def test_advanced_keys():
    print("Base URL:", BASE)
    if not COINBASE_ISS or not COINBASE_PEM_CONTENT:
        print("❌ Missing COINBASE_ISS or COINBASE_PEM_CONTENT")
        return

    ts = int(time.time())
    payload = {"iss": COINBASE_ISS, "iat": ts, "exp": ts + 300}

    try:
        token = jwt.encode(payload, COINBASE_PEM_CONTENT, algorithm="ES256")
    except Exception as e:
        print("❌ JWT creation failed:", e)
        return

    headers = {"Authorization": f"Bearer {token}"}

    # Try a couple of endpoints and print full request info
    endpoints = ["/accounts", "/v2/accounts", "/v2/brokerage/accounts", "/api/v3/trading/accounts"]
    for ep in endpoints:
        url = BASE.rstrip("/") + ep
        print("\n→ Testing", url)
        try:
            r = requests.get(url, headers=headers, timeout=10)
            print("Status:", r.status_code)
            print("Response (first 600 chars):", r.text[:600])
        except Exception as e:
            print("Request failed:", e)

if __name__ == "__main__":
    test_advanced_keys()
