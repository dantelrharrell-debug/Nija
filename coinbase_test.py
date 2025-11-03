import os, requests

API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

if not (API_KEY and API_SECRET and API_PASSPHRASE):
    raise RuntimeError("Missing Coinbase API credentials")

resp = requests.get(
    "https://api.coinbase.com/v2/accounts",
    headers={
        "CB-ACCESS-KEY": API_KEY,
        "CB-ACCESS-PASSPHRASE": API_PASSPHRASE,
        "CB-VERSION": "2025-11-02",
    },
)
print(resp.status_code, resp.text)
