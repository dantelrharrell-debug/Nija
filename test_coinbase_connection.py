from coinbase_advanced.client import Client
import os

client = Client(
    api_key=os.getenv("COINBASE_API_KEY"),
    pem_content=os.getenv("COINBASE_PEM_CONTENT"),
    org_id=os.getenv("COINBASE_ORG_ID")
)

try:
    accounts = client.accounts.list()
    print("✅ Connected. Accounts:", accounts)
except Exception as e:
    print("❌ Connection failed:", e)
