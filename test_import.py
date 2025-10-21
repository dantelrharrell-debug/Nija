import sys
import os

# Add local vendor folder to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# Import Coinbase client
from coinbase_advanced_py.client import CoinbaseClient

print("✅ CoinbaseClient loaded")
