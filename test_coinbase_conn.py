# test_coinbase_conn.py
import os, sys, json, logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

GITHUB_PAT = os.getenv("GITHUB_PAT")
if not GITHUB_PAT:
    print("❌ GITHUB_PAT missing in environment")
    sys.exit(2)

# install package if running locally (skip if already installed)
# Note: in container you should install with your start script instead
try:
    from coinbase_advanced.client import Client
except Exception as exc:
    print("coinbase_advanced not importable:", exc)
    print("Try installing: pip install 'git+https://<GITHUB_PAT>@github.com/coinbase/coinbase-advanced-python.git'")
    sys.exit(3)

key = os.getenv("COINBASE_API_KEY")
secret = os.getenv("COINBASE_API_SECRET")
passphrase = os.getenv("COINBASE_API_PASSPHRASE")
if not key or not secret:
    print("Missing COINBASE_API_KEY or COINBASE_API_SECRET")
    sys.exit(4)

print("Attempting to create client...")
try:
    client = Client(api_key=key, api_secret=secret, api_passphrase=passphrase)
    accounts = client.get_accounts()
    print("✅ Fetched accounts count:", len(accounts))
    # print first account summary
    if accounts:
        a = accounts[0]
        print(json.dumps({"id": a.get("id"), "currency": a.get("currency"), "balance": a.get("balance")}, indent=2))
    sys.exit(0)
except Exception as e:
    print("❌ Coinbase client error:", e)
    sys.exit(5)
