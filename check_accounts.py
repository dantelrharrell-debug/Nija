# check_account.py
from nija_client import CoinbaseClient

# Initialize client
client = CoinbaseClient()

# Check which account Nija is connected to
try:
    accounts = client.get_accounts()  # Coinbase Advanced API
    for acc in accounts:
        print(f"{acc['name']}: {acc['balance']['currency']} {acc['balance']['amount']}")
except Exception as e:
    print("Error fetching accounts:", e)
