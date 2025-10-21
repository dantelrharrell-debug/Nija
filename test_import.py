import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))
from coinbase_advanced_py.client import CoinbaseClient
print("✅ CoinbaseClient loaded")
