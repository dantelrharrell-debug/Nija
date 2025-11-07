from nija_client import CoinbaseClient

# Initialize client
client = CoinbaseClient()

try:
    accounts = client.get_accounts()
    print("✅ Accounts retrieved successfully!")
    for acc in accounts:
        print(f"Name: {acc['name']}, Currency: {acc['currency']}, Balance: {acc['balance']['amount']}")
except Exception as e:
    print("❌ Error accessing accounts:", e)
