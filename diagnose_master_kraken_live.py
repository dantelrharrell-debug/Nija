#!/usr/bin/env python3
"""
Diagnose Master Kraken Connection Issue
========================================

This script helps identify why the MASTER Kraken account is not connecting.

Run this to see:
1. Whether MASTER Kraken credentials are set
2. Whether they're valid (not whitespace)
3. Whether the connection succeeds
4. What the specific error is if it fails
"""

import os
import sys
import logging

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def main():
    """Run comprehensive Kraken Master diagnostics."""
    
    print("=" * 70)
    print("KRAKEN MASTER CONNECTION DIAGNOSTIC")
    print("=" * 70)
    print()
    
    # Step 1: Check if credentials are set
    print("Step 1: Checking Environment Variables")
    print("-" * 70)
    
    master_key = os.getenv("KRAKEN_MASTER_API_KEY", "")
    master_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "")
    
    # Also check legacy credentials
    legacy_key = os.getenv("KRAKEN_API_KEY", "")
    legacy_secret = os.getenv("KRAKEN_API_SECRET", "")
    
    # Check MASTER credentials
    if master_key:
        master_key_stripped = master_key.strip()
        if master_key != master_key_stripped:
            print("❌ KRAKEN_MASTER_API_KEY: SET but has leading/trailing whitespace")
            print(f"   Raw length: {len(master_key)}, Stripped length: {len(master_key_stripped)}")
        elif not master_key_stripped:
            print("❌ KRAKEN_MASTER_API_KEY: SET but contains ONLY whitespace")
        else:
            print(f"✅ KRAKEN_MASTER_API_KEY: SET ({len(master_key)} chars)")
    else:
        print("❌ KRAKEN_MASTER_API_KEY: NOT SET")
    
    if master_secret:
        master_secret_stripped = master_secret.strip()
        if master_secret != master_secret_stripped:
            print("❌ KRAKEN_MASTER_API_SECRET: SET but has leading/trailing whitespace")
            print(f"   Raw length: {len(master_secret)}, Stripped length: {len(master_secret_stripped)}")
        elif not master_secret_stripped:
            print("❌ KRAKEN_MASTER_API_SECRET: SET but contains ONLY whitespace")
        else:
            print(f"✅ KRAKEN_MASTER_API_SECRET: SET ({len(master_secret)} chars)")
    else:
        print("❌ KRAKEN_MASTER_API_SECRET: NOT SET")
    
    print()
    
    # Check legacy credentials
    if legacy_key or legacy_secret:
        print("ℹ️  Legacy Credentials Detected (fallback if MASTER not set):")
        if legacy_key:
            print(f"   KRAKEN_API_KEY: SET ({len(legacy_key)} chars)")
        if legacy_secret:
            print(f"   KRAKEN_API_SECRET: SET ({len(legacy_secret)} chars)")
        print()
    
    # Step 2: Determine which credentials will be used
    print("Step 2: Credential Selection")
    print("-" * 70)
    
    final_key = ""
    final_secret = ""
    cred_source = "NONE"
    
    if master_key.strip() and master_secret.strip():
        final_key = master_key.strip()
        final_secret = master_secret.strip()
        cred_source = "MASTER (KRAKEN_MASTER_*)"
        print(f"✅ Will use MASTER credentials")
    elif legacy_key.strip() and legacy_secret.strip():
        final_key = legacy_key.strip()
        final_secret = legacy_secret.strip()
        cred_source = "LEGACY (KRAKEN_API_*)"
        print(f"⚠️  Will use LEGACY credentials (fallback)")
        print("   Recommendation: Set KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET")
    else:
        print("❌ No valid credentials available")
        print()
        print("=" * 70)
        print("SOLUTION: Set MASTER Kraken Credentials")
        print("=" * 70)
        print()
        print("You need to set these environment variables in your deployment platform:")
        print("  KRAKEN_MASTER_API_KEY=<your-master-api-key>")
        print("  KRAKEN_MASTER_API_SECRET=<your-master-api-secret>")
        print()
        print("How to get credentials:")
        print("  1. Log in to Kraken: https://www.kraken.com/u/security/api")
        print("  2. Click 'Generate New Key'")
        print("  3. Set a description (e.g., 'NIJA Master Trading Bot')")
        print("  4. Enable these permissions:")
        print("     ✅ Query Funds")
        print("     ✅ Query Open Orders & Trades")
        print("     ✅ Query Closed Orders & Trades")
        print("     ✅ Create & Modify Orders")
        print("     ✅ Cancel/Close Orders")
        print("     ❌ Do NOT enable: Withdraw Funds (security risk)")
        print("  5. Copy the API Key and Private Key")
        print("  6. Add them to your deployment platform (Railway/Render)")
        print()
        print("For Railway:")
        print("  1. Go to your project dashboard")
        print("  2. Select your service")
        print("  3. Click 'Variables' tab")
        print("  4. Add the two variables above")
        print("  5. Deploy (Railway will auto-restart)")
        print()
        print("For Render:")
        print("  1. Go to your service dashboard")
        print("  2. Click 'Environment' tab")
        print("  3. Add the two variables above")
        print("  4. Click 'Save Changes'")
        print("  5. Click 'Manual Deploy' → 'Deploy latest commit'")
        print()
        return False
    
    print()
    
    # Step 3: Test connection
    print("Step 3: Testing Connection to Kraken")
    print("-" * 70)
    
    try:
        # Add bot directory to path
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
        
        from broker_manager import KrakenBroker, AccountType
        
        print(f"ℹ️  Creating KrakenBroker instance...")
        kraken = KrakenBroker(account_type=AccountType.MASTER)
        
        print(f"ℹ️  Attempting to connect using {cred_source}...")
        print()
        
        if kraken.connect():
            print("✅ MASTER KRAKEN CONNECTED SUCCESSFULLY!")
            print()
            
            # Try to get balance
            try:
                balance = kraken.get_account_balance()
                print(f"💰 Account Balance: ${balance:,.2f} USD")
                
                if balance >= 0.50:
                    print(f"✅ Account is FUNDED and ready to trade")
                else:
                    print(f"⚠️  Account balance is below minimum trading threshold ($0.50)")
                    print(f"   Add funds to enable trading")
            except Exception as e:
                print(f"⚠️  Could not fetch balance: {e}")
            
            print()
            print("=" * 70)
            print("DIAGNOSIS: MASTER KRAKEN IS WORKING!")
            print("=" * 70)
            print()
            print("If you're still not seeing MASTER Kraken in the bot logs,")
            print("the issue may be:")
            print("  1. Bot is not restarted after setting credentials")
            print("  2. Different environment (local vs production)")
            print("  3. Bot startup error before reaching Kraken connection")
            print()
            print("Next steps:")
            print("  1. Restart your bot deployment")
            print("  2. Check the startup logs for 'Attempting to connect Kraken Pro (MASTER)'")
            print("  3. Look for '✅ Kraken MASTER connected' message")
            print()
            return True
            
        else:
            print("❌ CONNECTION FAILED")
            print()
            
            # Check for specific error
            if hasattr(kraken, 'last_connection_error') and kraken.last_connection_error:
                error = kraken.last_connection_error
                print(f"Error: {error}")
                print()
                
                # Provide specific guidance based on error type
                if "permission" in error.lower() or "denied" in error.lower():
                    print("CAUSE: Insufficient API permissions")
                    print()
                    print("FIX:")
                    print("  1. Go to https://www.kraken.com/u/security/api")
                    print("  2. Find your API key")
                    print("  3. Enable these permissions:")
                    print("     ✅ Query Funds")
                    print("     ✅ Query Open Orders & Trades")
                    print("     ✅ Query Closed Orders & Trades")
                    print("     ✅ Create & Modify Orders")
                    print("     ✅ Cancel/Close Orders")
                    print("  4. Save changes")
                    print("  5. Wait 1-2 minutes")
                    print("  6. Restart the bot")
                    
                elif "nonce" in error.lower():
                    print("CAUSE: Invalid nonce error")
                    print()
                    print("FIX:")
                    print("  1. Wait 1-2 minutes")
                    print("  2. Restart the bot")
                    print("  3. If issue persists, regenerate API key")
                    
                elif "signature" in error.lower() or "invalid" in error.lower():
                    print("CAUSE: Invalid credentials")
                    print()
                    print("FIX:")
                    print("  1. Verify you copied the FULL API key and secret")
                    print("  2. Check for extra spaces or newlines")
                    print("  3. Regenerate the API key if needed")
                    print("  4. Update environment variables")
                    print("  5. Restart the bot")
                    
                elif "whitespace" in error.lower():
                    print("CAUSE: Credentials contain only whitespace")
                    print()
                    print("FIX:")
                    print("  1. Check environment variables in deployment platform")
                    print("  2. Remove any leading/trailing spaces")
                    print("  3. Ensure values are not empty")
                    print("  4. Re-save and restart")
                    
                else:
                    print("CAUSE: Unknown error")
                    print()
                    print("TROUBLESHOOTING:")
                    print("  1. Verify API key is not expired")
                    print("  2. Check Kraken API status: https://status.kraken.com")
                    print("  3. Try regenerating the API key")
                    print("  4. Check system time is synchronized")
                    
            else:
                print("No specific error information available")
                print()
                print("TROUBLESHOOTING:")
                print("  1. Check if Kraken SDK is installed: pip install krakenex pykrakenapi")
                print("  2. Verify API key is active")
                print("  3. Check Kraken API status: https://status.kraken.com")
            
            print()
            return False
            
    except ImportError as e:
        print(f"❌ IMPORT ERROR: {e}")
        print()
        print("CAUSE: Kraken SDK not installed")
        print()
        print("FIX:")
        print("  pip install krakenex pykrakenapi")
        print()
        return False
        
    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")
        print()
        import traceback
        traceback.print_exc()
        print()
        return False

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nDiagnostic interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
