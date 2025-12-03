# jwt_list_accounts.py
import os, time, jwt, requests

# Write PEM from env if present
pem_content = os.getenv("COINBASE_PEM_CONTENT")
if pem_content:
    with open("coinbase.pem", "w") as f:
        f.write(pem_content)
    os.chmod("coinbase.pem", 0o600)

PEM_PATH = "coinbase.pem"
ISS = os.getenv("COINBASE_ISS")  # the JWT key id / issuer if needed

def make_jwt():
    now = int(time.time())
    payload = {"iat": now}
    # If Coinbase expects an "iss" or other claims, include them:
    if ISS:
        payload["iss"] = ISS
    with open(PEM_PATH, "rb") as f:
        private_key = f.read()
    token = jwt.encode(payload, private_key, algorithm="RS256")
    return token

def list_accounts_jwt():
    token = make_jwt()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    # Choose the correct endpoint your JWT key supports:
    url = "https://api.coinbase.com/v2/accounts"
    r = requests.get(url, headers=headers, timeout=15)
    print("status", r.status_code)
    print(r.text)

if __name__ == "__main__":
    if not os.path.exists(PEM_PATH):
        raise SystemExit("coinbase.pem missing; set COINBASE_PEM_CONTENT")
    list_accounts_jwt()
