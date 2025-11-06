from nija_client import CoinbaseClient

client = CoinbaseClient()

accounts = client.get_accounts()
if accounts:
    print("✅ API connection OK. Accounts fetched successfully:")
    for acc in accounts:
        print(f"{acc['currency']}: {acc['balance']}")
    print("\nYour bot is ready to trade live.")
else:
    print("❌ No accounts fetched. Check API keys and permissions.")
