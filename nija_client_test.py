import os, time, jwt, requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

with open(os.environ["COINBASE_PEM_PATH"], "rb") as f:
    private_key = serialization.load_pem_private_key(f.read(), password=None, backend=default_backend())

iat = int(time.time())
payload = {"sub": os.environ["COINBASE_ORG_ID"], "iat": iat, "exp": iat+300}
token = jwt.encode(payload, private_key, algorithm="ES256")
print("JWT:", token)

headers = {"Authorization": f"Bearer {token}", "CB-VERSION": "2025-01-01"}
resp = requests.get("https://api.coinbase.com/v2/accounts", headers=headers)
print(resp.status_code, resp.text)
