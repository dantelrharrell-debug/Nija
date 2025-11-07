from nija_client import CoinbaseClient

if __name__ == "__main__":
    client = CoinbaseClient()
    accounts = client.get_accounts()
    if not accounts:
        print("No accounts returned. Check key permissions or IP allowlist ❌")
    else:
        print("Connected accounts:")
        for a in accounts:
            name = a.get("name", "<unknown>")
            bal = a.get("balance", {})
            print(f"{name}: {bal.get('amount', '0')} {bal.get('currency', '?')}")
