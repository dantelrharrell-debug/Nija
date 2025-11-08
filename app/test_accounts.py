from nija_hmac_client import CoinbaseClient

client = CoinbaseClient()
status, accounts = client.get_accounts()

if status != 200:
    raise Exception(f"Failed to fetch accounts: {accounts}")

print("Accounts fetched successfully:")
for acct in accounts.get("data", []):
    print(f"{acct['name']} ({acct['currency']}): {acct['balance']['amount']}")
