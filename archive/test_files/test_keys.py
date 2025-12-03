import os
import time
import datetime
import requests
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# --- Load env ---
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_API_KEY_ID = os.getenv("COINBASE_API_KEY_ID")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

SUB = f"/organizations/{COINBASE_ORG_ID}/apiKeys/{COINBASE_API_KEY_ID}"

# --- Prepare private key ---
private_key = COINBASE_PEM_CONTENT.replace("\\n", "\n").encode("utf-8")
private_key_obj = serialization.load_pem_private_key(private_key, password=None, backend=default_backend())

# --- Generate JWT ---
def generate_jwt(path: str, method: str = "GET") -> str:
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

# --- Test key permissions ---
path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/key_permissions"
url = f"https://api.coinbase.com{path}"

token = generate_jwt(path)
resp = requests.get(url, headers={
    "Authorization": f"Bearer {token}",
    "CB-VERSION": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
    "Content-Type": "application/json"
}, timeout=10)

print("HTTP Status:", resp.status_code)
print(resp.text)
