from nija_client import CoinbaseClient

try:
    c = CoinbaseClient()
    acct = next((a for a in c.get_accounts() if a.get('primary')), None)
    if acct:
        bal = acct['balance']
        print(f"Primary account: {acct['name']}")
        print(f"Balance: {bal['amount']} {bal['currency']}")
        print("Account is ready for trading ✅")
    else:
        print("No primary account found. Check API permissions ❌")
except Exception as e:
    print("Error connecting to Coinbase:", e)
    if hasattr(e, 'response'):
        print("HTTP status code:", e.response.status_code)
