from nija_client import CoinbaseClient

def main():
    try:
        # Initialize client
        client = CoinbaseClient()
        print("✅ CoinbaseClient initialized successfully.\n")
        
        # Fetch all accounts
        accounts = client.get_all_accounts()
        print("💰 All Coinbase accounts and balances:")
        for acct in accounts:
            currency = acct.get("currency")
            balance = acct.get("balance", {}).get("amount", 0)
            acct_type = acct.get("type")
            print(f" - {currency} | Balance: {balance} | Type: {acct_type}")
        
        # Optional: check USD balance used for trading
        usd_balance = next(
            (float(acct.get("balance", {}).get("amount", 0)) 
             for acct in accounts if acct.get("currency") == "USD"), 0
        )
        print(f"\n🔹 USD account balance used for trading: {usd_balance}\n")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
