import os
import requests
import time
import jwt as pyjwt

pem = os.getenv("COINBASE_PEM_CONTENT")
iss = os.getenv("COINBASE_ISS")
base = os.getenv("COINBASE_BASE")

payload = {"iat": int(time.time()), "exp": int(time.time())+300, "iss": iss}
token = pyjwt.encode(payload, pem, algorithm="ES256")

headers = {"Authorization": f"Bearer {token}"}
r = requests.get(f"{base}/accounts", headers=headers)
print(r.status_code, r.text)
