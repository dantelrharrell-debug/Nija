cat > debug_client_full.py << 'EOF'
#!/usr/bin/env python3
import sys
import os
import traceback

# --- USER INFO ---
USER = "ypuser"
NAME = "Dante Harrell"

# Automatically set the path to your vendor folder
current_dir = os.path.dirname(os.path.abspath(__file__))
vendor_path = os.path.join(current_dir, "vendor")
sys.path.insert(0, vendor_path)

try:
    from coinbase_advanced_py.client import CoinbaseClient
except Exception as e:
    print("⚠️ CoinbaseClient import failed:", e)
    traceback.print_exc()
    print("✅ Continuing in safe debug mode without live API access")
    CoinbaseClient = None

def main():
    print("=== DEBUG CLIENT FULL ===")
    print(f"User: {USER}")
    print(f"Name: {NAME}")
    print("Current folder:", current_dir)
    print("Vendor folder added to path:", vendor_path)

    if CoinbaseClient is None:
        print("✅ Running in safe debug mode. No live API calls.")
    else:
        # Replace with your real API keys to test live
        API_KEY = "YOUR_API_KEY"
        API_SECRET = "YOUR_API_SECRET"
        API_PASSPHRASE = "YOUR_API_PASSPHRASE"

        try:
            client = CoinbaseClient(api_key=API_KEY, api_secret=API_SECRET, passphrase=API_PASSPHRASE)
            accounts = client.get_accounts()
            if accounts:
                print("✅ Coinbase client connected successfully. Accounts:")
                for acc in accounts:
                    print(f" - {acc['currency']}: {acc['balance']}")
            else:
                print("⚠️ Connected but no accounts found.")
        except Exception as e:
            print("⚠️ Error connecting to Coinbase:")
            traceback.print_exc()

if __name__ == "__main__":
    main()
EOF
