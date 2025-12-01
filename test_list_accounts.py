from nija_coinbase_client import NijaCoinbaseClient

client = NijaCoinbaseClient()
accounts = client.list_accounts()

print("\n=== YOUR COINBASE ACCOUNTS ===")
if isinstance(accounts, dict) and "accounts" in accounts:
    accounts = accounts["accounts"]

for a in accounts:
    print("-------------------------------")
    print("ID:       ", a.get("uuid") or a.get("id"))
    print("Currency: ", a.get("currency"))
    print("Balance:  ", a.get("available_balance", a.get("balance")))
    print("Type:     ", a.get("type"))
    print("Status:   ", a.get("status"))
