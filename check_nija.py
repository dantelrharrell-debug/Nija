from nija_client import NijaCoinbaseClient

client = NijaCoinbaseClient()

# Check balances
balances = client.get_balances()
print("Balances:", balances)

# Check recent trades
trades = client.get_recent_trades(limit=5)
print("Recent trades:", trades)
