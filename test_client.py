import sys, os
sys.path.insert(0, os.path.join(os.getcwd(), 'vendor'))

# test_client.py
from nija_client import client, CLIENT

if client:
    print("Client attached:", client)
else:
    print("Simulation mode active.")

import sys, os

# Add vendor folder to Python path
sys.path.insert(0, os.path.join(os.getcwd(), 'vendor'))

# Safe import
try:
    from coinbase_advanced_py.client import CoinbaseClient
    print("✅ CoinbaseClient imported successfully")
except Exception as e:
    print(f"⚠️ Import failed: {e}")
