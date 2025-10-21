# test_import.py - merged version

# Local test import
print("Local test import")

# Remote test import
print("Remote test import")

import sys
import os

# Add local vendor folder to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

# Import Coinbase client
from coinbase_advanced_py.client import CoinbaseClient

print("✅ CoinbaseClient loaded")
