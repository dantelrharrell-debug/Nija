# check_accounts.py
from nija_client import CoinbaseClient

# Initialize the Coinbase client
client = CoinbaseClient()

# Fetch account balances
accounts = client.get_accounts()

# Check if any accounts are returned
if accounts:
    print("✅ API connection OK. Accounts fetched successfully:")
    for acc in accounts:
        print(f"{acc['currency']}: {acc['balance']}")
    print("\nYour bot is ready to trade live.")
else:
    print("❌ No accounts fetched. Check API keys and permissions.")
