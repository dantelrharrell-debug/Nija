from nija_coinbase_client import CoinbaseClient
import json

client = CoinbaseClient()
status, data = client.get_accounts()
print("Status:", status)
print(json.dumps(data, indent=2) if isinstance(data, dict) else data)
