from nija_client import CoinbaseClient

def main():
    try:
        client = CoinbaseClient()
    except Exception as e:
        print(f"❌ Error creating CoinbaseClient: {e}")
        return

    try:
        accounts = client.get_all_accounts()
        print("✅ Accounts fetched:")
        for acct in accounts:
            currency = acct.get("currency")
            balance = acct.get("balance", {}).get("amount", 0)
            print(f"{currency}: {balance}")
    except Exception as e:
        print(f"❌ Failed to fetch accounts: {e}")

    usd_balance = client.get_usd_spot_balance()
    print(f"💰 USD Spot Balance: {usd_balance}")

if __name__ == "__main__":
    main()
