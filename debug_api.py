#!/usr/bin/env python3
import os
import sys
from dotenv import load_dotenv

load_dotenv()

print("Python version:", sys.version)
print("Current dir:", os.getcwd())
print("\n=== TESTING API ===\n")

try:
    print("1. Checking for .env...")
    if os.path.exists('.env'):
        print("   ✅ .env file exists")
    else:
        print("   ❌ .env file NOT found")
        sys.exit(1)
    
    print("\n2. Loading credentials...")
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    
    if api_key:
        print(f"   ✅ API Key: {api_key[:30]}...")
    else:
        print("   ❌ COINBASE_API_KEY not set")
    
    if api_secret:
        print(f"   ✅ API Secret: {api_secret[:30]}...")
    else:
        print("   ❌ COINBASE_API_SECRET not set")
    
    print("\n3. Importing Coinbase...")
    from coinbase.rest import RESTClient
    print("   ✅ Import successful")
    
    print("\n4. Creating client...")
    client = RESTClient(
        api_key=api_key,
        api_secret=api_secret
    )
    print("   ✅ Client created")
    
    print("\n5. Fetching accounts...")
    resp = client.get_accounts()
    print(f"   ✅ Response type: {type(resp)}")
    print(f"   ✅ Response: {resp}")
    
except Exception as e:
    print(f"\n❌ ERROR: {e}")
    print(f"Type: {type(e).__name__}")
    import traceback
    print("\nFull traceback:")
    traceback.print_exc()
    sys.exit(1)

print("\n✅ SUCCESS")
