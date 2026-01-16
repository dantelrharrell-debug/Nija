#!/usr/bin/env python3
"""
QUICK FIX: Enable Master Kraken Trading

This script helps diagnose and fix issues with master Kraken not connecting.
It checks all possible credential configurations and provides step-by-step fix instructions.
"""

import os
import sys

def print_header(text):
    """Print a formatted header"""
    print("\n" + "=" * 70)
    print(text.center(70))
    print("=" * 70 + "\n")

def print_section(text):
    """Print a formatted section header"""
    print("\n" + "-" * 70)
    print(text)
    print("-" * 70)

def check_env_var(name):
    """Check if an environment variable is set and valid"""
    raw_value = os.getenv(name, "")
    stripped_value = raw_value.strip()
    
    if not raw_value:
        return False, "NOT SET"
    elif raw_value != stripped_value:
        if stripped_value:
            return True, f"SET with whitespace (length: {len(stripped_value)} chars after strip)"
        else:
            return False, "SET but empty after stripping whitespace (INVALID)"
    else:
        return True, f"SET ({len(stripped_value)} chars)"

def main():
    print_header("MASTER KRAKEN TRADING - QUICK FIX")
    
    print("This script will:")
    print("  1. Check if master Kraken credentials are configured")
    print("  2. Check if user Kraken credentials are configured")
    print("  3. Identify the issue preventing master Kraken from trading")
    print("  4. Provide exact steps to fix the issue")
    
    # Check Master Credentials
    print_section("📋 STEP 1: Check Master Kraken Credentials")
    
    master_key_valid, master_key_status = check_env_var("KRAKEN_MASTER_API_KEY")
    master_secret_valid, master_secret_status = check_env_var("KRAKEN_MASTER_API_SECRET")
    legacy_key_valid, legacy_key_status = check_env_var("KRAKEN_API_KEY")
    legacy_secret_valid, legacy_secret_status = check_env_var("KRAKEN_API_SECRET")
    
    print(f"   KRAKEN_MASTER_API_KEY:    {master_key_status}")
    print(f"   KRAKEN_MASTER_API_SECRET: {master_secret_status}")
    print(f"   KRAKEN_API_KEY (legacy):  {legacy_key_status}")
    print(f"   KRAKEN_API_SECRET (legacy): {legacy_secret_status}")
    
    # Determine if master is configured
    master_configured = False
    if master_key_valid and master_secret_valid:
        print("\n✅ Master Kraken credentials ARE configured (new format)")
        master_configured = True
        cred_type = "NEW"
    elif legacy_key_valid and legacy_secret_valid:
        print("\n✅ Master Kraken credentials ARE configured (legacy format)")
        master_configured = True
        cred_type = "LEGACY"
    else:
        print("\n❌ Master Kraken credentials are NOT properly configured")
        cred_type = None
    
    # Check User Credentials
    print_section("📋 STEP 2: Check User Kraken Credentials")
    
    # Find all KRAKEN_USER_* environment variables
    user_credentials = {}
    for key in os.environ:
        if key.startswith("KRAKEN_USER_") and key.endswith("_API_KEY"):
            username = key[len("KRAKEN_USER_"):-len("_API_KEY")]
            secret_key = f"KRAKEN_USER_{username}_API_SECRET"
            
            key_valid, key_status = check_env_var(key)
            secret_valid, secret_status = check_env_var(secret_key)
            
            user_credentials[username] = (key_valid and secret_valid)
            print(f"\nUser: {username}")
            print(f"   {key}: {key_status}")
            print(f"   {secret_key}: {secret_status}")
    
    if not user_credentials:
        print("\n⚪ No user Kraken credentials found")
        users_configured = False
    else:
        users_configured = any(user_credentials.values())
        configured_count = sum(user_credentials.values())
        print(f"\n📊 Summary: {configured_count}/{len(user_credentials)} user(s) configured")
    
    # Diagnosis
    print_section("🔍 STEP 3: Diagnosis")
    
    if master_configured and users_configured:
        print("✅ Both master and user credentials are configured")
        print("\nIf master is still not connecting, the issue is likely:")
        print("  • Invalid/incorrect API credentials")
        print("  • Insufficient API key permissions")
        print("  • Whitespace/formatting issues in credentials")
        print("  • Nonce errors (temporary)")
        
        print("\n🔧 RECOMMENDED ACTIONS:")
        print("  1. Check deployment logs for specific error messages")
        print("  2. Verify API key has all required permissions on Kraken website")
        print("  3. Try regenerating the API key if errors persist")
        print("  4. Contact support if issue continues")
        
    elif not master_configured and users_configured:
        print("❌ ISSUE IDENTIFIED:")
        print("   • User Kraken accounts: CONFIGURED ✅")
        print("   • Master Kraken account: NOT CONFIGURED ❌")
        print("\nThis is why users can trade on Kraken but master cannot.")
        
        print("\n" + "🔧 SOLUTION".center(70, "="))
        print("\nYou need to set master Kraken credentials in your deployment environment.")
        print("\n📝 OPTION 1: Set New Format Credentials (Recommended)")
        print("   Add these environment variables in Railway/Render:")
        print("   • KRAKEN_MASTER_API_KEY=<your-api-key>")
        print("   • KRAKEN_MASTER_API_SECRET=<your-api-secret>")
        
        print("\n📝 OPTION 2: Set Legacy Credentials (Backward Compatible)")
        print("   Add these environment variables instead:")
        print("   • KRAKEN_API_KEY=<your-api-key>")
        print("   • KRAKEN_API_SECRET=<your-api-secret>")
        
        print("\n📖 HOW TO GET CREDENTIALS:")
        print("   1. Go to: https://www.kraken.com/u/security/api")
        print("   2. Click 'Generate New Key'")
        print("   3. Description: 'NIJA Master Trading Bot'")
        print("   4. Enable these permissions:")
        print("      ✅ Query Funds")
        print("      ✅ Query Open Orders & Trades")
        print("      ✅ Query Closed Orders & Trades")
        print("      ✅ Create & Modify Orders")
        print("      ✅ Cancel/Close Orders")
        print("      ❌ Withdraw Funds (security - do NOT enable)")
        print("   5. Copy the API Key and Private Key")
        
        print("\n📖 HOW TO ADD TO RAILWAY:")
        print("   1. Go to Railway project → Your service → Variables")
        print("   2. Click 'New Variable'")
        print("   3. Add KRAKEN_MASTER_API_KEY and paste the API key")
        print("   4. Add KRAKEN_MASTER_API_SECRET and paste the Private Key")
        print("   5. Click 'Save' (Railway auto-restarts)")
        
        print("\n📖 HOW TO ADD TO RENDER:")
        print("   1. Go to Render service → Environment tab")
        print("   2. Click 'Add Environment Variable'")
        print("   3. Add KRAKEN_MASTER_API_KEY and paste the API key")
        print("   4. Add KRAKEN_MASTER_API_SECRET and paste the Private Key")
        print("   5. Click 'Save Changes'")
        print("   6. Click 'Manual Deploy' → 'Deploy latest commit'")
        
        print("\n⚠️  IMPORTANT:")
        print("   • Use a DIFFERENT API key for master than for users")
        print("   • Using the same key causes nonce conflicts")
        print("   • Master and users must have separate API keys")
        
    elif master_configured and not users_configured:
        print("ℹ️  Master configured, but no user accounts configured")
        print("   This is normal if you only want master trading.")
        
    else:
        print("❌ Neither master nor user Kraken credentials are configured")
        print("   Kraken trading is completely disabled.")
        print("\nSet at least master OR user credentials to enable Kraken trading.")
    
    # Connection Test
    if master_configured:
        print_section("🔌 STEP 4: Test Master Kraken Connection")
        print("Attempting to connect to Kraken with master credentials...")
        
        try:
            # Import broker modules
            try:
                from bot.broker_manager import KrakenBroker, AccountType
            except ImportError:
                # Fallback
                bot_path = os.path.join(os.path.dirname(__file__), 'bot')
                if bot_path not in sys.path:
                    sys.path.insert(0, bot_path)
                from broker_manager import KrakenBroker, AccountType
            
            # Create and test master broker
            master_broker = KrakenBroker(account_type=AccountType.MASTER)
            if master_broker.connect():
                print("✅ SUCCESS! Master Kraken connected")
                try:
                    balance = master_broker.get_account_balance()
                    print(f"   Account balance: ${balance:,.2f}")
                    print("\n🎉 Master Kraken is ready to trade!")
                except Exception as e:
                    print(f"   ⚠️  Balance check failed: {e}")
                    print("   Connection successful but balance query failed")
            else:
                print("❌ FAILED: Could not connect to master Kraken")
                if hasattr(master_broker, 'last_connection_error') and master_broker.last_connection_error:
                    print(f"   Error: {master_broker.last_connection_error}")
                else:
                    print("   No error details available")
                
                print("\n🔧 TROUBLESHOOTING:")
                print("   • Check that credentials are correct")
                print("   • Verify API key has required permissions")
                print("   • Check for whitespace in environment variables")
                print("   • Try regenerating the API key")
        
        except Exception as e:
            print(f"❌ Connection test failed: {e}")
            print("\n   This might be because:")
            print("   • Kraken SDK not installed (run: pip install krakenex pykrakenapi)")
            print("   • Import error in broker modules")
            print("   • Network connectivity issue")
    
    # Summary
    print_section("📊 SUMMARY")
    
    status_lines = []
    if master_configured:
        status_lines.append("✅ Master Kraken: CONFIGURED")
    else:
        status_lines.append("❌ Master Kraken: NOT CONFIGURED")
    
    if users_configured:
        configured_users = [u for u, v in user_credentials.items() if v]
        status_lines.append(f"✅ User Kraken: CONFIGURED ({', '.join(configured_users)})")
    else:
        status_lines.append("⚪ User Kraken: NOT CONFIGURED")
    
    for line in status_lines:
        print(line)
    
    if not master_configured and users_configured:
        print("\n" + "!" * 70)
        print("ACTION REQUIRED: Set master Kraken credentials")
        print("See SOLUTION section above for step-by-step instructions")
        print("!" * 70)
    elif master_configured:
        print("\n✅ Master credentials are set - check logs for connection status")
    
    print("\n" + "=" * 70)
    print("For more help, see: KRAKEN_MASTER_NOT_CONNECTING_JAN_16_2026.md")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
