# nija_debug.py
import os
import sys
import requests  # needed for HTTPError handling

# Load .env if available
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"ℹ️ Loaded environment variables from {env_path}")
    else:
        print("ℹ️ No .env file found; using system environment variables")
except ImportError:
    print("⚠️ python-dotenv not installed; skipping .env load")

# Debug info: working directory & files
print("ℹ️ Current working directory:", os.getcwd())
print("ℹ️ Files in project root:", os.listdir("."))

# Import Coinbase client
try:
    from nija_client import CoinbaseClient
    print("✅ Successfully imported CoinbaseClient")
except ImportError as e:
    print("❌ ImportError:", e)
    sys.exit(1)

def check_env():
    """Check if required Coinbase API keys exist. Passphrase is optional."""
    missing = []
    for key in ["COINBASE_API_KEY", "COINBASE_API_SECRET"]:
        if not os.getenv(key):
            missing.append(key)
    if missing:
        print(f"❌ Missing environment variables: {', '.join(missing)}")
        return False

    if not os.getenv("COINBASE_API_PASSPHRASE"):
        print("⚠️ COINBASE_API_PASSPHRASE not set. Ignored for Coinbase Advanced API.")
    else:
        print("✅ COINBASE_API_PASSPHRASE is set (legacy API).")

    print("✅ Required environment variables are set.")
    return True

def test_client():
    """Test CoinbaseClient instantiation and fetching accounts."""
    try:
        client = CoinbaseClient()
        try:
            accounts = client.get_accounts()  # Make sure this method exists
            print("✅ CoinbaseClient instantiated successfully.")
            print("Accounts:", accounts)
        except requests.exceptions.HTTPError as e:
            print(f"❌ Coinbase API returned an HTTP error: {e}")
        except Exception as e:
            print(f"❌ Error fetching accounts: {e}")
    except Exception as e:
        print("❌ Error initializing CoinbaseClient:", e)

if __name__ == "__main__":
    if check_env():
        test_client()
