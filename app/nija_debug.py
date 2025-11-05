from nija_client import CoinbaseClient, calculate_position_size, get_usd_spot_balance, get_all_accounts

def main():
    print("✅ Starting Nija preflight check...")

    try:
        # Initialize client
        client = CoinbaseClient()
        print("✅ CoinbaseClient initialized successfully.")
    except Exception as e:
        print(f"❌ Error creating CoinbaseClient: {e}")
        return

    # Fetch USD balance
    try:
        usd_balance = client.get_usd_spot_balance()
        print(f"ℹ️ USD Spot Balance: ${usd_balance:.2f}")
    except Exception as e:
        print(f"❌ Failed to fetch USD Spot balance: {e}")
        usd_balance = 0

    # Calculate position size
    try:
        if usd_balance > 0:
            trade_size = calculate_position_size(usd_balance)
            print(f"ℹ️ Suggested position size: ${trade_size:.2f}")
        else:
            print("⚠️ USD balance zero or unavailable; cannot calculate position size.")
    except Exception as e:
        print(f"❌ Failed to calculate position size: {e}")

    # Fetch all accounts (debug)
    try:
        accounts = client.get_all_accounts()
        print(f"ℹ️ Total accounts fetched: {len(accounts)}")
    except Exception as e:
        print(f"❌ Failed to fetch all accounts: {e}")


if __name__ == "__main__":
    main()
