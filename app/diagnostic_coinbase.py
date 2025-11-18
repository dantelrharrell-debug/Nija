import sys
import importlib
import os
import traceback

print("=== Coinbase Advanced SDK Diagnostic ===\n")

# Step 1: Check if package is installed
try:
    spec = importlib.util.find_spec("coinbase_advanced_py")
    if spec is None:
        print("❌ coinbase-advanced-py not found in environment!")
    else:
        import coinbase_advanced_py
        print(f"✅ coinbase-advanced-py is installed, version: {coinbase_advanced_py.__version__}")
except Exception as e:
    print(f"❌ Error checking coinbase-advanced-py: {e}")
    traceback.print_exc()

# Step 2: Try importing AdvancedClient
try:
    from coinbase_advanced_py.client import AdvancedClient
    print("✅ Successfully imported AdvancedClient")
except ImportError as e:
    print(f"❌ Failed to import AdvancedClient: {e}")
    traceback.print_exc()

# Step 3: Try instantiating AdvancedClient (with dummy PEM/ORG_ID)
try:
    PEM = os.environ.get("COINBASE_PEM_CONTENT", "dummy_pem_content")
    ORG_ID = os.environ.get("COINBASE_ORG_ID", "dummy_org_id")

    client = AdvancedClient(pem=PEM, org_id=ORG_ID)
    print("✅ AdvancedClient instantiated (check PEM/ORG_ID validity separately)")
except Exception as e:
    print(f"❌ Failed to instantiate AdvancedClient: {e}")
    traceback.print_exc()

print("\n=== Diagnostic Complete ===")
