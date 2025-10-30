from nija_coinbase_jwt import get_jwt_token
import requests
import os

print("[NIJA] Running preflight checks...")

jwt_token = get_jwt_token()
headers = {"Authorization": f"Bearer {jwt_token}"}
API_BASE = "https://api.coinbase.com"

# Test request
resp = requests.get(f"{API_BASE}/v2/accounts", headers=headers)
if resp.status_code == 200:
    print("[NIJA] Coinbase API authentication successful!")
else:
    print("[NIJA] Coinbase authentication failed:", resp.text)
