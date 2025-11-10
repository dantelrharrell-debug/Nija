from app.nija_client import CoinbaseClient  # use 'app' package

# Initialize client
client = CoinbaseClient()

# Fetch accounts
try:
    accounts = client.fetch_advanced_accounts()  # current method
    for acc in accounts:
        print(f"{acc.get('name', acc.get('id', '<unknown>'))}: "
              f"{acc.get('balance', {}).get('currency', '')} "
              f"{acc.get('balance', {}).get('amount', '')}")
except Exception as e:
    print("Error fetching accounts:", e)
