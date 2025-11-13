# app/test_coinbase.py
from coinbase.rest import RESTClient
import os

# Load environment variables
api_key    = os.environ.get("COINBASE_API_KEY")
api_secret = os.environ.get("COINBASE_PEM_CONTENT")
org_id     = os.environ.get("COINBASE_ORG_ID")

full_api_key = api_key
secret = api_secret

# Initialize client
client = RESTClient(api_key=full_api_key, api_secret=secret)

# Test call
accounts = client.get_accounts()
print(accounts)
