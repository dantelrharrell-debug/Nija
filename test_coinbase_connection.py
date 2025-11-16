import os
import time
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- Load credentials from environment ---
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

# Make sure PEM has real newlines
private_key = COINBASE_PEM_CONTENT.replace("\\n", "\n").encode()
private_key_obj = serialization.load_pem_private_key(private_key, password=None, backend=default_backend())

# Full API key path
SUB = f"/organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_API_KEY_ID}"

# --- Generate JWT ---
def generate_jwt(path, method="GET"):
    iat = int(time.time())
    payload = {
        "iat": iat,
        "exp": iat + 120,
        "sub": SUB,
        "request_path": path,
        "method": method.upper(),
        "jti": f"test-{iat}"
    }
    headers = {"alg": "ES256", "kid": COINBASE_API_KEY_ID}
    token = jwt.encode(payload, private_key_obj, algorithm="ES256", headers=headers)
    return token

# --- Test fetch accounts ---
path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
url = "https://api.coinbase.com" + path

token = generate_jwt(path)

try:
    resp = requests.get(url, headers={
        "Authorization": f"Bearer {token}",
        "CB-VERSION": "2025-11-16",
        "Content-Type": "application/json"
    }, timeout=10)

    print("HTTP Status:", resp.status_code)
    print(resp.text[:500])  # show first 500 chars
except Exception as e:
    print("Exception fetching accounts:", e)
