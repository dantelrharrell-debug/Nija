cat > list_coinbase_accounts.py <<'PY'
from nija_client import CoinbaseClient

client = CoinbaseClient()
accounts = client.get_accounts()

if not accounts:
    print("⚠️ No accounts returned or unauthorized request.")
else:
    for acc in accounts:
        name = acc.get("name", "<unknown>")
        bal = acc.get("balance", {})
        print(f"{name}: {bal.get('amount','0')} {bal.get('currency','?')}")
PY
