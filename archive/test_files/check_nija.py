from nija_client import CoinbaseClient  # <- correct class name

client = CoinbaseClient(advanced=True)  # enable Advanced/JWT mode

# Example: check accounts/balances
accounts = client.get_accounts()
for acc in accounts:
    currency = acc.get("currency") or acc.get("currency_code")
    amt = acc.get("available_balance") or (acc.get("balance") or {}).get("amount") or acc.get("available")
    print(f"{currency}: {amt}")

# If you want a helper USD balance
from nija_balance_helper import get_usd_balance
usd_balance = get_usd_balance(client)
print("USD Balance:", usd_balance)
