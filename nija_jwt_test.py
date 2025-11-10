import os, time, requests, jwt as pyjwt

pem = os.getenv("COINBASE_PEM_CONTENT")
iss = os.getenv("COINBASE_ISS")
base = os.getenv("COINBASE_BASE")  # Should be https://api.cdp.coinbase.com

payload = {"iat": int(time.time()), "exp": int(time.time())+300, "iss": iss}
token = pyjwt.encode(payload, pem, algorithm="ES256")
if isinstance(token, bytes): token = token.decode("utf-8")

# Use ONLY Advanced endpoint first
url = f"{base}/api/v3/brokerage/accounts"
headers = {"Authorization": f"Bearer {token}"}
r = requests.get(url, headers=headers)
print("Status code:", r.status_code)
print("Response:", r.text)
