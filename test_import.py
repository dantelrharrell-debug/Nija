<<<<<<< HEAD
import sys
import os

# Add local vendor folder to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# Import Coinbase client
from coinbase_advanced_py.client import CoinbaseClient

print("✅ CoinbaseClient loaded")
=======
import sys, os, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))
try:
    from coinbase_advanced_py.client import CoinbaseClient
    print("✅ CoinbaseClient loaded successfully")
except Exception:
    traceback.print_exc()
>>>>>>> 5fcdf82 (Fix deploy issues)
