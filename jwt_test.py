import os, time, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import requests

key_path = "/opt/railway/secrets/coinbase.pem"
org_id = "ce77e4ea-ecca-42ec-912a-b6b4455ab9d0"  # your Org ID

with open(key_path, "rb") as f:
    key = serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())

iat = int(time.time())
payload = {"sub": org_id, "iat": iat, "exp": iat+300}
token = jwt.encode(payload, key, algorithm="ES256")
print("JWT:", token)

headers = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-01-01"}
resp = requests.get("https://api.coinbase.com/v2/accounts", headers=headers)
print(resp.status_code, resp.text)
