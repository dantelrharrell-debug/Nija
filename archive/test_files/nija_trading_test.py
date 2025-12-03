# nija_trading_test.py
from vendor.coinbase_advanced_py.client import CoinbaseClient
from dotenv import load_dotenv
import os

# Load .env automatically
load_dotenv()

# Check that keys are loaded
api_key = os.getenv("API_KEY")
api_secret = os.getenv("API_SECRET")
passphrase = os.getenv("API_PASSPHRASE")

print("Loaded API_KEY:", api_key is not None)
print("Loaded API_SECRET:", api_secret is not None)
print("Loaded PASSPHRASE:", passphrase is not None)

if not all([api_key, api_secret, passphrase]):
    print("❌ One or more API keys are missing. Check your .env file.")
    exit()

# Initialize Coinbase client
try:
    client = CoinbaseClient(
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
        sandbox=False  # Must be False for live
    )

    # Fetch and print account balances
    accounts = client.get_accounts()
    if accounts:
        print("✅ Coinbase accounts retrieved:")
        for acc in accounts:
            print(acc)
    else:
        print("⚠️ No accounts returned. Check API keys and permissions.")

except Exception as e:
    print("❌ Error connecting to Coinbase:", e)
