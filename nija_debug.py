# nija_debug.py
import os
import sys

# --- Load .env if available ---
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

# --- Debug info: show current working directory and files ---
print("ℹ️ Current working directory:", os.getcwd())
print("ℹ️ Files in project root:", os.listdir("."))

# --- Attempt import of CoinbaseClient ---
try:
    from nija_client import CoinbaseClient
    print("✅ Successfully imported CoinbaseClient")
except ImportError as e:
    print("❌ ImportError:", e)
    print("Make sure nija_client.py exists and defines 'CoinbaseClient'")
    sys.exit(1)

# --- Check required environment variables ---
def check_env():
    """Ensure API keys exist; passphrase is optional and ignored."""
    missing = []
    for key in ["COINBASE_API_KEY", "COINBASE_API_SECRET"]:
        if not os.getenv(key):
            missing.append(key)
    if missing:
        print(f"❌ Missing required environment variables: {', '.join(missing)}")
        return False

    if not os.getenv("COINBASE_API_PASSPHRASE"):
        print("⚠️ COINBASE_API_PASSPHRASE not set. Ignored for Coinbase Advanced API.")
    else:
        print("ℹ️ COINBASE_API_PASSPHRASE detected but ignored (optional).")

    print("✅ Required environment variables are set.")
    return True

# --- Test CoinbaseClient ---
def test_client():
    """Instantiate CoinbaseClient and fetch accounts (fails gracefully if unauthorized)."""
    try:
        client = CoinbaseClient()
        accounts = client.get_accounts()  # Make sure this method exists
        print("✅ CoinbaseClient instantiated successfully.")
        print("Accounts:", accounts)
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 401:
            print("❌ Unauthorized (401). Check API_KEY and API_SECRET.")
        else:
            print("❌ HTTPError:", e)
    except Exception as e:
        print("❌ Error initializing CoinbaseClient:", e)

# --- Main ---
if __name__ == "__main__":
    if check_env():
        test_client()
