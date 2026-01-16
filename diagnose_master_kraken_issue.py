#!/usr/bin/env python3
"""
Diagnose why Kraken MASTER is not connecting while USER accounts succeed.

This script checks:
1. Master credential configuration
2. User credential configuration  
3. Differences between master and user setup
4. Connection test for both
"""

import os
import sys

print("=" * 70)
print("KRAKEN MASTER vs USER CONNECTION DIAGNOSTIC")
print("=" * 70)
print()

# Check Master Credentials
print("📋 MASTER CREDENTIALS CHECK")
print("-" * 70)

master_key_raw = os.getenv("KRAKEN_MASTER_API_KEY", "")
master_secret_raw = os.getenv("KRAKEN_MASTER_API_SECRET", "")
legacy_key_raw = os.getenv("KRAKEN_API_KEY", "")
legacy_secret_raw = os.getenv("KRAKEN_API_SECRET", "")

# Strip credentials
master_key = master_key_raw.strip()
master_secret = master_secret_raw.strip()
legacy_key = legacy_key_raw.strip()
legacy_secret = legacy_secret_raw.strip()

# Check each credential
def check_credential(name, raw_value, stripped_value):
    """Check and report credential status."""
    if not raw_value:
        print(f"❌ {name}: NOT SET")
        return False
    elif raw_value != stripped_value:
        print(f"⚠️  {name}: MALFORMED (contains whitespace)")
        print(f"   Raw length: {len(raw_value)} chars")
        print(f"   Stripped length: {len(stripped_value)} chars")
        if not stripped_value:
            print(f"   → Empty after stripping (CRITICAL ERROR)")
            return False
        return True
    else:
        print(f"✅ {name}: SET ({len(stripped_value)} chars)")
        return True

master_key_ok = check_credential("KRAKEN_MASTER_API_KEY", master_key_raw, master_key)
master_secret_ok = check_credential("KRAKEN_MASTER_API_SECRET", master_secret_raw, master_secret)

print()
print("Legacy fallback check:")
legacy_key_ok = check_credential("KRAKEN_API_KEY (legacy)", legacy_key_raw, legacy_key)
legacy_secret_ok = check_credential("KRAKEN_API_SECRET (legacy)", legacy_secret_raw, legacy_secret)

print()
print("Master credential summary:")
if master_key_ok and master_secret_ok:
    print("✅ Master credentials are CONFIGURED (new format)")
    master_configured = True
elif legacy_key_ok and legacy_secret_ok:
    print("✅ Master credentials are CONFIGURED (legacy format)")
    master_configured = True
else:
    print("❌ Master credentials are NOT properly configured")
    master_configured = False

print()
print("=" * 70)

# Check User Credentials
print("📋 USER CREDENTIALS CHECK")
print("-" * 70)

# Dynamically find all KRAKEN_USER_* credentials
user_results = {}
all_env_vars = dict(os.environ)

# Find all user credential pairs
user_prefixes = set()
for key in all_env_vars:
    if key.startswith("KRAKEN_USER_") and key.endswith("_API_KEY"):
        # Extract the username portion (between KRAKEN_USER_ and _API_KEY)
        username = key[len("KRAKEN_USER_"):-len("_API_KEY")]
        user_prefixes.add(username)

if not user_prefixes:
    print("⚪ No user credentials found")
    print("   (No environment variables matching KRAKEN_USER_*_API_KEY)")
else:
    for username in sorted(user_prefixes):
        # Convert username to user_id format (e.g., "TANIA" -> "tania_gilbert")
        # This is for display purposes only - we use the env var name directly
        user_id = username.lower().replace("_", " ").title().replace(" ", "_")
        
        print(f"\nUser: {user_id}")
        print(f"Environment variable prefix: KRAKEN_USER_{username}_")
        
        user_key_raw = os.getenv(f"KRAKEN_USER_{username}_API_KEY", "")
        user_secret_raw = os.getenv(f"KRAKEN_USER_{username}_API_SECRET", "")
        
        user_key = user_key_raw.strip()
        user_secret = user_secret_raw.strip()
        
        key_ok = check_credential(f"  KRAKEN_USER_{username}_API_KEY", user_key_raw, user_key)
        secret_ok = check_credential(f"  KRAKEN_USER_{username}_API_SECRET", user_secret_raw, user_secret)
        
        user_results[user_id] = (key_ok and secret_ok)

print()
print("User credential summary:")
for user_id, configured in user_results.items():
    status = "✅ CONFIGURED" if configured else "❌ NOT CONFIGURED"
    print(f"  {user_id}: {status}")

print()
print("=" * 70)

# Comparison
print("🔍 MASTER vs USER COMPARISON")
print("-" * 70)

if master_configured and any(user_results.values()):
    print("⚠️  CONFIGURATION MISMATCH:")
    print(f"   Master: {'✅ CONFIGURED' if master_configured else '❌ NOT CONFIGURED'}")
    for user_id, configured in user_results.items():
        print(f"   User {user_id}: {'✅ CONFIGURED' if configured else '❌ NOT CONFIGURED'}")
    print()
    print("This is unusual! Both should typically be configured.")
    print()
elif not master_configured and any(user_results.values()):
    print("❌ ISSUE FOUND: Users configured but Master is not!")
    print()
    print("This explains why user accounts connect but master doesn't.")
    print()
    print("SOLUTION:")
    print("1. Set these environment variables in Railway/Render:")
    print("   KRAKEN_MASTER_API_KEY=<your-master-api-key>")
    print("   KRAKEN_MASTER_API_SECRET=<your-master-api-secret>")
    print()
    print("2. Get credentials from: https://www.kraken.com/u/security/api")
    print("3. Required permissions:")
    print("   ✅ Query Funds")
    print("   ✅ Query Open Orders & Trades")
    print("   ✅ Query Closed Orders & Trades")
    print("   ✅ Create & Modify Orders")
    print("   ✅ Cancel/Close Orders")
    print()
    print("4. Restart the deployment after adding credentials")
elif master_configured and not any(user_results.values()):
    print("✅ Master configured, but no users configured")
    print("This is normal if you only want master trading.")
elif not master_configured and not any(user_results.values()):
    print("❌ Neither master nor users are configured")
    print("Kraken trading won't work without credentials.")
else:
    print("✅ Both master and users are configured")
    print("If master still doesn't connect, the issue is likely:")
    print("  1. Invalid/incorrect credentials")
    print("  2. Permission errors (API key lacks required permissions)")
    print("  3. API key is for wrong account type")

print()
print("=" * 70)

# Connection Test
print("🔌 CONNECTION TEST")
print("-" * 70)

if not master_configured:
    print("⏭️  Skipping connection test (master credentials not configured)")
else:
    print("Testing master Kraken connection...")
    print()
    
    try:
        # Try to import broker modules - use proper package import
        try:
            from bot.broker_manager import KrakenBroker, AccountType
        except ImportError:
            # Fallback: add bot directory to path only if direct import fails
            import sys
            bot_path = os.path.join(os.path.dirname(__file__), 'bot')
            if bot_path not in sys.path:
                sys.path.insert(0, bot_path)
            from broker_manager import KrakenBroker, AccountType
        
        # Test master connection
        print("Creating master KrakenBroker instance...")
        master_broker = KrakenBroker(account_type=AccountType.MASTER)
        
        print("Attempting to connect...")
        connected = master_broker.connect()
        
        if connected:
            print("✅ MASTER KRAKEN CONNECTED!")
            try:
                balance = master_broker.get_account_balance()
                print(f"   Balance: ${balance:,.2f}")
            except Exception as e:
                print(f"   (Balance check failed: {e})")
        else:
            print("❌ MASTER KRAKEN CONNECTION FAILED")
            if hasattr(master_broker, 'last_connection_error') and master_broker.last_connection_error:
                print(f"   Error: {master_broker.last_connection_error}")
            else:
                print("   No error details available")
    
    except Exception as e:
        print(f"❌ Connection test failed with exception: {e}")
        import traceback
        traceback.print_exc()

print()
print("=" * 70)
print("DIAGNOSTIC COMPLETE")
print("=" * 70)
