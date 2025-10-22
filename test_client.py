# Add vendor folder to Python path
import sys, os
sys.path.insert(0, os.path.join(os.getcwd(), 'vendor'))

# Import your Nija client
from nija_client import client, CLIENT

# Check if client attached
if client:
    print("Client attached:", client)
else:
    print("Simulation mode active.")

# Optional: test direct import of CoinbaseClient
try:
    from coinbase_advanced_py.client import CoinbaseClient
    print("✅ CoinbaseClient imported successfully")
except Exception as e:
    print(f"⚠️ Import failed: {e}")
