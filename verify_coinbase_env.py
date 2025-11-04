import os
from coinbase.wallet.client import Client

print("=== Checking Coinbase credentials ===")

api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET")
api_passphrase = os.getenv("COINBASE_API_PASSPHRASE")

if not api_key or not api_secret:
    print("❌ Missing COINBASE_API_KEY or COINBASE_API_SECRET in environment")
    exit(1)

# If the secret was pasted with \n sequences, convert them
if "\\n" in api_secret:
    api_secret = api_secret.replace("\\n", "\n")

print("✅ API key loaded (first 6 chars):", api_key[:6], "...")
print("✅ Passphrase loaded:", bool(api_passphrase))

# Test connection
client = Client(api_key, api_secret)

try:
    accounts = client.get_accounts()
    print("✅ Connection successful! Found", len(accounts["data"]), "accounts.")
    for a in accounts["data"]:
        print(f"   - {a['name']}: {a['balance']['amount']} {a['balance']['currency']}")
except Exception as e:
    print("❌ Connection failed:", type(e).__name__, e)
