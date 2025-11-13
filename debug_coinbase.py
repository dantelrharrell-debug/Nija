import os, time, requests, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

API_KEY_ID = os.environ["COINBASE_API_KEY"]
PEM = os.environ["COINBASE_PEM"].replace("\\n","\n")
ORG_ID = os.environ["COINBASE_ORG_ID"]

private_key = serialization.load_pem_private_key(PEM.encode(), password=None, backend=default_backend())

path = f"/api/v3/brokerage/organizations/{ORG_ID}/accounts"
url = f"https://api.coinbase.com{path}"
iat = int(time.time())
payload = {
    "iat": iat,
    "exp": iat + 120,
    "sub": API_KEY_ID,
    "request_path": path,
    "method": "GET"
}
headers = {"alg":"ES256","kid":API_KEY_ID}
token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)

resp = requests.get(url, headers={"Authorization": f"Bearer {token}", "CB-VERSION": "2025-11-12"})
print(resp.status_code, resp.text)
