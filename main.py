from coinbase_advanced.client import Client
import os

client = Client(
    api_key=os.getenv("COINBASE_API_KEY"),
    pem_content=os.getenv("COINBASE_PEM_CONTENT"),
    org_id=os.getenv("COINBASE_ORG_ID")
)

# Example: Fetch balances
accounts = client.accounts.list()
for acct in accounts.data:
    print(acct)
