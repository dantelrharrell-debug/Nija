# test_import.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vendor"))

try:
    from coinbase_advanced_py.client import CoinbaseClient
    print("✅ CoinbaseClient loaded")
except Exception as e:
    print("❌ Failed:", e)
