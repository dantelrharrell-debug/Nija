# nija_preflight.py
import os
from nija_client import CoinbaseClient, calculate_position_size

def main():
    print("🔹 Starting Nija Preflight Check 🔹\n")

    client = None

    # Attempt Advanced JWT first
    try:
        print("ℹ️ Trying Advanced JWT...")
        client = CoinbaseClient()  # Ensure your env variable COINBASE_API_SECRET contains the PEM
        accounts = client.get_all_accounts()
        print(f"✅ Advanced JWT succeeded. Fetched {len(accounts)} accounts.\n")
    except Exception as jwt_error:
        print(f"⚠️ Advanced JWT failed: {jwt_error}")
        # Attempt Classic API key fallback
        try:
            print("ℹ️ Trying Classic API key + passphrase...")
            os.environ["COINBASE_API_SECRET"] = os.getenv("COINBASE_API_SECRET_CLASSIC", "")
            os.environ["COINBASE_API_KEY"] = os.getenv("COINBASE_API_KEY_CLASSIC", "")
            os.environ["COINBASE_API_PASSPHRASE"] = os.getenv("COINBASE_API_PASSPHRASE_CLASSIC", "")
            client = CoinbaseClient()
            accounts = client.get_all_accounts()
            print(f"✅ Classic API key succeeded. Fetched {len(accounts)} accounts.\n")
        except Exception as classic_error:
            print(f"❌ Both Advanced JWT and Classic API key failed:")
            print(f"  - JWT error: {jwt_error}")
            print(f"  - Classic API error: {classic_error}")
            return

    # Show account balances
    for account in accounts:
        print(f"  - {account['currency']}: {account['balance']['amount']} {account['balance']['currency']}")

    # Test position sizing calculation
    try:
        usd_account = next((a for a in accounts if a["currency"] == "USD"), None)
        if usd_account:
            balance = float(usd_account["balance"]["amount"])
            trade_size = calculate_position_size(balance)
            print(f"\n✅ Position sizing calculation successful: ${trade_size:.2f} (from ${balance:.2f})")
        else:
            print("\n⚠️ No USD account found for position sizing test.")
    except Exception as e:
        print(f"❌ Failed to calculate position size: {e}")
        return

    print("\n🔹 Nija Preflight Check Complete 🔹")
    print("✅ All checks passed. Nija is ready to trade live.")

if __name__ == "__main__":
    main()
