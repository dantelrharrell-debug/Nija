from nija_client import CoinbaseClient, calculate_position_size

def main():
    print("✅ Starting Nija preflight check...")

    try:
        client = CoinbaseClient()
    except Exception as e:
        print(f"❌ Failed to initialize CoinbaseClient: {e}")
        return

    # Fetch USD balance safely
    try:
        usd_balance = client.get_usd_spot_balance()
        print(f"✅ USD Spot Balance: ${usd_balance:.2f}")
    except Exception as e:
        print(f"❌ Failed to fetch USD Spot balance: {e}")
        usd_balance = 0

    # Calculate position size only if balance > 0
    try:
        if usd_balance > 0:
            trade_size = calculate_position_size(usd_balance)
            print(f"✅ Calculated Trade Size: ${trade_size:.2f}")
        else:
            print("⚠️ USD balance is 0. Skipping position size calculation.")
    except Exception as e:
        print(f"❌ Failed to calculate position size: {e}")

    print("✅ Nija preflight check complete.")

if __name__ == "__main__":
    main()
