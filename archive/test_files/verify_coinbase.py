# verify_coinbase.py
try:
    from coinbase_advanced.client import Client
    print("✅ coinbase_advanced_py imported successfully!")
except ModuleNotFoundError:
    print("❌ ERROR: coinbase_advanced_py not found.")
except Exception as e:
    print(f"❌ ERROR: Import failed with exception: {e}")
