# debug_coinbase_jwt.py
import os
import time
import jwt  # pyjwt
import requests

# Load env vars
API_KEY = os.environ.get("COINBASE_API_KEY")
ORG_ID = os.environ.get("COINBASE_ORG_ID")
PEM_RAW = os.environ.get("COINBASE_PEM_CONTENT", "")

# Ensure PEM line breaks
PEM_FIXED = PEM_RAW.replace("\\n", "\n") if "\\n" in PEM_RAW else PEM_RAW

# Try both sub formats
subs = [
    f"organizations/{ORG_ID}/apiKeys/{API_KEY}",
    API_KEY
]

url = "https://api.coinbase.com/v2/accounts"

for sub in subs:
    payload = {
        "sub": sub,
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,  # 1 min expiry
        "jti": str(int(time.time()*1000)),
    }

    token = jwt.encode(payload, PEM_FIXED, algorithm="ES256")
    headers = {"Authorization": f"Bearer {token}"}

    print(f"Testing sub: {sub}")
    try:
        resp = requests.get(url, headers=headers)
        print(f"Status Code: {resp.status_code}")
        print(f"Response: {resp.text}\n")
    except Exception as e:
        print(f"Error: {e}\n")
