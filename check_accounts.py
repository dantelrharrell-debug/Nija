from nija_client import CoinbaseClient

client = CoinbaseClient()
accounts = client.get_accounts()  # Should return your real Coinbase balances
for acct in accounts:
    print(acct['currency'], acct['balance'])
