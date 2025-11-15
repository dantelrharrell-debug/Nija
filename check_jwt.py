# check_jwt.py
import os, time, requests, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

PEM_PATH = os.environ.get("COINBASE_PEM_PATH", "/app/coinbase.pem")
ORG_ID = os.environ.get("COINBASE_ORG_ID")
KID = os.environ.get("COINBASE_JWT_KID") or None

with open(PEM_PATH, "rb") as f:
    data = f.read()
print("PEM bytes:", len(data))

key = serialization.load_pem_private_key(data, password=None, backend=default_backend())
iat = int(time.time())
payload = {"sub": ORG_ID, "iat": iat, "exp": iat + 300}
headers = {"kid": KID} if KID else None

token = jwt.encode(payload, key, algorithm="ES256", headers=headers)
print("JWT preview:", token[:80])

h = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-01-01"}
r = requests.get("https://api.coinbase.com/v2/accounts", headers=h, timeout=12)
print("Status:", r.status_code)
print("Body (first 400 chars):", r.text[:400])
