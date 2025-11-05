# nija_preflight.py
import os
from nija_client import CoinbaseClient, calculate_position_size

def main():
    print("🔹 Starting Nija Preflight Check 🔹\n")

    try:
        # Initialize Coinbase client
        client = CoinbaseClient()
        print("✅ CoinbaseClient initialized successfully.\n")
    except Exception as e:
        print(f"❌ Failed to initialize CoinbaseClient: {e}")
        return

    # Fetch accounts
    try:
        accounts = client.get_all_accounts()
        print(f"✅ Fetched {len(accounts)} accounts successfully.")
        for account in accounts:
            print(f"  - {account['currency']}: {account['balance']['amount']} {account['balance']['currency']}")
    except Exception as e:
        print(f"❌ Failed to fetch accounts: {e}")
        return

    # Test position sizing calculation
    try:
        if accounts:
            # Use first USD account as example
            usd_account = next((a for a in accounts if a["currency"] == "USD"), None)
            if usd_account:
                balance = float(usd_account["balance"]["amount"])
                trade_size = calculate_position_size(balance)
                print(f"✅ Position sizing calculation successful: ${trade_size:.2f} (from ${balance:.2f})")
            else:
                print("⚠️ No USD account found for position sizing test.")
    except Exception as e:
        print(f"❌ Failed to calculate position size: {e}")
        return

    print("\n🔹 Nija Preflight Check Complete 🔹")
    print("✅ All checks passed. Nija is ready to trade live.")

if __name__ == "__main__":
    main()
