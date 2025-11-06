import os
from nija_client import CoinbaseClient

client = CoinbaseClient()

# Check account info
accounts = client.get_accounts()  # should return account balances
for acc in accounts:
    print(acc['currency'], acc['balance'])
