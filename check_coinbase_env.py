import os, time, requests, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

COINBASE_API_KEY_FULL = os.getenv("COINBASE_API_KEY_FULL")
COINBASE_ORG_ID = os.getenv("COINBASE_ORG_ID")
COINBASE_PEM_PATH = os.getenv("COINBASE_PEM_PATH")
COINBASE_PEM_CONTENT = os.getenv("COINBASE_PEM_CONTENT")

# Load PEM
pem_text = COINBASE_PEM_CONTENT.replace("\\n", "\n") if COINBASE_PEM_CONTENT else open(COINBASE_PEM_PATH).read()
private_key = serialization.load_pem_private_key(pem_text.encode(), password=None, backend=default_backend())

# Use full path for kid
kid = COINBASE_API_KEY_FULL
api_key_id = COINBASE_API_KEY_FULL.split("/")[-1]

# Build JWT
path = f"/api/v3/brokerage/organizations/{COINBASE_ORG_ID}/accounts"
iat = int(time.time())
payload = {"iat": iat, "exp": iat + 120, "sub": api_key_id, "request_path": path, "method": "GET"}
token = jwt.encode(payload, private_key, algorithm="ES256", headers={"alg":"ES256","kid":kid})

# Test fetch
url = f"https://api.coinbase.com{path}"
resp = requests.get(url, headers={"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-12"})
print("HTTP status:", resp.status_code)
print("Response:", resp.text)
