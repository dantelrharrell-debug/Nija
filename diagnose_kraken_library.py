#!/usr/bin/env python3
"""
Diagnostic script to check if Kraken library is installed and can be imported.
This will help identify if the issue is with the library installation.
"""

import sys
import os

print("=" * 70)
print("KRAKEN LIBRARY DIAGNOSTIC")
print("=" * 70)
print()

# Check 1: Can we import krakenex?
print("Test 1: Importing krakenex library...")
try:
    import krakenex
    print("✅ SUCCESS: krakenex imported successfully")
    print(f"   Version: {krakenex.__version__ if hasattr(krakenex, '__version__') else 'version not available'}")
    print(f"   Location: {krakenex.__file__ if hasattr(krakenex, '__file__') else 'location not available'}")
except ImportError as e:
    print("❌ FAILED: krakenex cannot be imported")
    print(f"   Error: {e}")
    print()
    print("   FIX: Install krakenex with:")
    print("   pip install krakenex==2.2.2")
    sys.exit(1)
except Exception as e:
    print(f"❌ UNEXPECTED ERROR: {e}")
    sys.exit(1)

print()

# Check 2: Can we import pykrakenapi?
print("Test 2: Importing pykrakenapi library...")
try:
    import pykrakenapi
    print("✅ SUCCESS: pykrakenapi imported successfully")
    print(f"   Location: {pykrakenapi.__file__ if hasattr(pykrakenapi, '__file__') else 'location not available'}")
except ImportError as e:
    print("❌ FAILED: pykrakenapi cannot be imported")
    print(f"   Error: {e}")
    print()
    print("   FIX: Install pykrakenapi with:")
    print("   pip install pykrakenapi==0.3.2")
    sys.exit(1)
except Exception as e:
    print(f"❌ UNEXPECTED ERROR: {e}")
    sys.exit(1)

print()

# Check 3: Can we create a Kraken API instance?
print("Test 3: Creating krakenex API instance...")
try:
    api = krakenex.API()
    print("✅ SUCCESS: krakenex.API() instance created")
except Exception as e:
    print(f"❌ FAILED: Cannot create API instance: {e}")
    sys.exit(1)

print()

# Check 4: Check credentials
print("Test 4: Checking environment variables...")
kraken_master_key = os.getenv("KRAKEN_MASTER_API_KEY", "")
kraken_master_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "")

if kraken_master_key and kraken_master_secret:
    print("✅ KRAKEN_MASTER_API_KEY: SET")
    print(f"   Length: {len(kraken_master_key)} characters")
    print()
    print("✅ KRAKEN_MASTER_API_SECRET: SET")
    print(f"   Length: {len(kraken_master_secret)} characters")
else:
    print("⚠️  WARNING: KRAKEN_MASTER_API_KEY and/or KRAKEN_MASTER_API_SECRET not set")
    print()
    print("   Legacy fallback check...")
    kraken_key = os.getenv("KRAKEN_API_KEY", "")
    kraken_secret = os.getenv("KRAKEN_API_SECRET", "")
    
    if kraken_key and kraken_secret:
        print("✅ KRAKEN_API_KEY: SET (legacy)")
        print(f"   Length: {len(kraken_key)} characters")
        print()
        print("✅ KRAKEN_API_SECRET: SET (legacy)")
        print(f"   Length: {len(kraken_secret)} characters")
    else:
        print("❌ No Kraken credentials found (neither new nor legacy format)")

print()

# Check 5: Check user credentials
print("Test 5: Checking user account credentials...")
user_accounts = [
    ("DAIVON", "daivon_frazier"),
    ("TANIA", "tania_gilbert")
]

for env_name, user_id in user_accounts:
    key_var = f"KRAKEN_USER_{env_name}_API_KEY"
    secret_var = f"KRAKEN_USER_{env_name}_API_SECRET"
    
    key = os.getenv(key_var, "")
    secret = os.getenv(secret_var, "")
    
    if key and secret:
        print(f"✅ User: {user_id}")
        print(f"   {key_var}: SET ({len(key)} chars)")
        print(f"   {secret_var}: SET ({len(secret)} chars)")
    else:
        print(f"⚠️  User: {user_id} - Credentials NOT SET")

print()
print("=" * 70)
print("DIAGNOSIS COMPLETE")
print("=" * 70)
print()

# Final verdict
if kraken_master_key and kraken_master_secret:
    print("✅ LIBRARY: Installed and working")
    print("✅ CREDENTIALS: Configured (master account)")
    print()
    print("NEXT STEPS:")
    print("1. Check bot logs for connection errors")
    print("2. Run: python3 test_kraken_connection_live.py")
    print("3. If still failing, check API key permissions at:")
    print("   https://www.kraken.com/u/security/api")
else:
    print("⚠️  LIBRARY: Installed but credentials not configured")
    print()
    print("FIX: Set environment variables in Railway/Render:")
    print("   KRAKEN_MASTER_API_KEY=<your-api-key>")
    print("   KRAKEN_MASTER_API_SECRET=<your-api-secret>")
