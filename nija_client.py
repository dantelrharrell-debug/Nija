import os
from coinbase_advanced_py.client import CoinbaseClient  # ✅ Correct import

# Load API keys from environment
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", "")  # can be empty

if not API_KEY or not API_SECRET:
    raise RuntimeError("❌ ERROR: Coinbase API keys not set!")

# Initialize the Coinbase client
client = CoinbaseClient(
    api_key=API_KEY,
    api_secret=API_SECRET,
    api_passphrase=API_PASSPHRASE
)

def start_trading():
    """Main trading loop."""
    print("🔁 Nija bot is live! Starting trading loop...")
    # Add your live trading logic here
    pass
