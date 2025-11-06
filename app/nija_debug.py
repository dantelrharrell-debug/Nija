# nija_debug.py
import os
from nija_client import CoinbaseClient

def check_env():
    """Check if all required Coinbase API keys are set."""
    missing = []
    for key in ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_API_PASSPHRASE"]:
        if not os.getenv(key):
            missing.append(key)
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        return False
    print("✅ All required environment variables are set.")
    return True

def test_client():
    """Test CoinbaseClient instantiation and fetching accounts."""
    try:
        client = CoinbaseClient()
        accounts = client.get_accounts()  # Make sure this method exists
        print("✅ CoinbaseClient instantiated successfully.")
        print("Accounts:", accounts)
    except Exception as e:
        print("❌ Error initializing CoinbaseClient:", e)

if __name__ == "__main__":
    if check_env():
        test_client()
