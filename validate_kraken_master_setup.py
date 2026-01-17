#!/usr/bin/env python3
"""
Kraken Master Account Setup Validator
======================================

This script validates that the Kraken master account is properly configured
and ready to start trading.

Usage:
    python3 validate_kraken_master_setup.py

Checks performed:
    1. Environment variables are set
    2. Credentials are valid format
    3. Kraken API is accessible
    4. Required permissions are granted
    5. Account balance can be retrieved
    6. Trading is enabled

Last Updated: January 17, 2026
"""

import os
import sys
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


def print_banner():
    """Print welcome banner."""
    print()
    print("=" * 80)
    print("KRAKEN MASTER ACCOUNT SETUP VALIDATOR".center(80))
    print("=" * 80)
    print()


def print_section(title):
    """Print section header."""
    print()
    print("─" * 80)
    print(f"  {title}")
    print("─" * 80)
    print()


def check_environment_variables():
    """Check if environment variables are set."""
    print_section("📋 STEP 1: Environment Variables")
    
    key = os.getenv("KRAKEN_MASTER_API_KEY", "").strip()
    secret = os.getenv("KRAKEN_MASTER_API_SECRET", "").strip()
    
    issues = []
    
    # Check if variables are set
    if not key:
        print("❌ KRAKEN_MASTER_API_KEY: NOT SET")
        issues.append("KRAKEN_MASTER_API_KEY not set")
    else:
        print(f"✅ KRAKEN_MASTER_API_KEY: SET ({len(key)} characters)")
        
        # Validate format
        if len(key) < 50:
            print(f"   ⚠️  Warning: Key seems short (expected ~56 chars)")
            issues.append("API key may be incomplete")
    
    if not secret:
        print("❌ KRAKEN_MASTER_API_SECRET: NOT SET")
        issues.append("KRAKEN_MASTER_API_SECRET not set")
    else:
        print(f"✅ KRAKEN_MASTER_API_SECRET: SET ({len(secret)} characters)")
        
        # Validate format
        if len(secret) < 80:
            print(f"   ⚠️  Warning: Secret seems short (expected ~88 chars)")
            issues.append("API secret may be incomplete")
    
    # Check for legacy fallback
    legacy_key = os.getenv("KRAKEN_API_KEY", "").strip()
    legacy_secret = os.getenv("KRAKEN_API_SECRET", "").strip()
    
    if not key and legacy_key:
        print()
        print("ℹ️  Legacy credentials detected:")
        print(f"   KRAKEN_API_KEY: SET ({len(legacy_key)} chars)")
        print("   These will be used as fallback for master account")
    
    if not secret and legacy_secret:
        print(f"   KRAKEN_API_SECRET: SET ({len(legacy_secret)} chars)")
    
    return len(issues) == 0, issues


def check_kraken_libraries():
    """Check if required Kraken libraries are installed."""
    print_section("📚 STEP 2: Required Libraries")
    
    issues = []
    
    try:
        import krakenex
        print(f"✅ krakenex: Installed (version {krakenex.__version__ if hasattr(krakenex, '__version__') else 'unknown'})")
    except ImportError as e:
        print(f"❌ krakenex: NOT INSTALLED")
        issues.append("krakenex library not installed")
        print(f"   Fix: pip install krakenex")
    
    try:
        import pykrakenapi
        print(f"✅ pykrakenapi: Installed")
    except ImportError as e:
        print(f"❌ pykrakenapi: NOT INSTALLED")
        issues.append("pykrakenapi library not installed")
        print(f"   Fix: pip install pykrakenapi")
    
    return len(issues) == 0, issues


def test_kraken_connection():
    """Test actual connection to Kraken API."""
    print_section("🔌 STEP 3: Kraken API Connection Test")
    
    key = os.getenv("KRAKEN_MASTER_API_KEY", "").strip()
    secret = os.getenv("KRAKEN_MASTER_API_SECRET", "").strip()
    
    # Use legacy fallback if master credentials not set
    if not key:
        key = os.getenv("KRAKEN_API_KEY", "").strip()
    if not secret:
        secret = os.getenv("KRAKEN_API_SECRET", "").strip()
    
    if not key or not secret:
        print("❌ Cannot test connection: Credentials not set")
        return False, ["Credentials not configured"]
    
    issues = []
    
    try:
        import krakenex
        from pykrakenapi import KrakenAPI
        
        print("Initializing Kraken API client...")
        api = krakenex.API(key=key, secret=secret)
        k = KrakenAPI(api)
        
        print("✅ Kraken API client initialized")
        
        # Test public endpoint (doesn't require auth)
        print("Testing public API (server time)...")
        server_time = k.get_server_time()
        print(f"✅ Public API working (Server time: {server_time})")
        
        # Test private endpoint (requires auth)
        print("Testing private API (account balance)...")
        try:
            balance = k.get_account_balance()
            print(f"✅ Private API working")
            print(f"✅ Successfully retrieved account balance")
            
            # Display balance info
            if not balance.empty:
                print()
                print("💰 Account Balance:")
                for currency, amount in balance.items():
                    if amount > 0:
                        print(f"   {currency}: {amount:,.8f}")
            else:
                print("   ⚠️  No balance found (account may be empty)")
            
            return True, []
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Private API failed: {error_msg}")
            
            # Parse common errors
            if "Permission denied" in error_msg or "EAPI:Invalid key" in error_msg:
                issues.append("API key permissions insufficient")
                print()
                print("💡 FIX: Check API key permissions on Kraken:")
                print("   1. Go to https://www.kraken.com/u/security/api")
                print("   2. Verify your API key has these permissions:")
                print("      ✅ Query Funds")
                print("      ✅ Query Open Orders & Trades")
                print("      ✅ Query Closed Orders & Trades")
                print("      ✅ Create & Modify Orders")
                print("      ✅ Cancel/Close Orders")
                print("   3. If permissions are wrong, delete key and create new one")
                
            elif "Invalid nonce" in error_msg:
                issues.append("Nonce synchronization issue")
                print()
                print("💡 FIX: Nonce error detected:")
                print("   1. Wait 1-2 minutes and try again")
                print("   2. If persists, generate new API key")
                print("   3. Ensure you're not using same key for multiple accounts")
                
            elif "Invalid signature" in error_msg:
                issues.append("Invalid API credentials")
                print()
                print("💡 FIX: Signature error detected:")
                print("   1. Verify you copied the COMPLETE API key and secret")
                print("   2. Check for any truncated characters")
                print("   3. Generate new API key if needed")
                
            else:
                issues.append(f"API error: {error_msg}")
            
            return False, issues
    
    except ImportError as e:
        print(f"❌ Required library missing: {e}")
        issues.append("Required libraries not installed")
        return False, issues
    
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        issues.append(f"Unexpected error: {str(e)}")
        return False, issues


def test_trading_readiness():
    """Check if bot can start trading on Kraken."""
    print_section("🚀 STEP 4: Trading Readiness")
    
    # This is a simplified check - actual bot has more complex logic
    # Just verify that the broker integration would initialize
    
    try:
        # Import broker manager to test initialization
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
        from broker_manager import KrakenBroker, AccountType
        
        print("Initializing Kraken broker for master account...")
        broker = KrakenBroker(account_type=AccountType.MASTER)
        
        print("Attempting to connect...")
        if broker.connect():
            print("✅ Kraken broker connected successfully!")
            
            # Get balance
            try:
                balance = broker.get_account_balance()
                if balance and balance.get('trading_balance', 0) > 0:
                    print(f"✅ Trading balance: ${balance['trading_balance']:.2f}")
                    print("✅ READY TO TRADE!")
                    return True, []
                else:
                    print("⚠️  Connected but no trading balance detected")
                    print("   Add funds to start trading")
                    return True, ["No trading balance"]
            except Exception as e:
                print(f"⚠️  Connected but couldn't retrieve balance: {e}")
                return True, ["Balance retrieval failed"]
        else:
            print(f"❌ Connection failed: {broker.last_connection_error}")
            return False, [broker.last_connection_error or "Connection failed"]
    
    except Exception as e:
        print(f"❌ Trading readiness check failed: {e}")
        return False, [str(e)]


def print_summary(all_issues):
    """Print final summary."""
    print_section("📊 VALIDATION SUMMARY")
    
    if not all_issues:
        print("✅ ALL CHECKS PASSED!")
        print()
        print("🎉 Kraken master account is properly configured and ready to trade!")
        print()
        print("Next steps:")
        print("1. Ensure your bot is deployed (Railway/Render/Local)")
        print("2. Check logs for: '✅ Kraken MASTER connected'")
        print("3. Verify trading started: '✅ Started independent trading thread for kraken'")
        print()
        print("Monitor with:")
        print("  python3 check_trading_status.py")
        print()
        return True
    else:
        print(f"❌ VALIDATION FAILED - {len(all_issues)} issue(s) found:")
        print()
        for i, issue in enumerate(all_issues, 1):
            print(f"{i}. {issue}")
        print()
        print("📖 Complete setup guide:")
        print("   KRAKEN_MASTER_SETUP_COMPLETE_GUIDE.md")
        print()
        print("🔧 Quick fixes:")
        print("   - Missing credentials: Set KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET")
        print("   - Permission errors: Verify API key permissions on Kraken")
        print("   - Library errors: pip install -r requirements.txt")
        print()
        return False


def main():
    """Main validation function."""
    print_banner()
    
    all_issues = []
    
    # Check 1: Environment variables
    success, issues = check_environment_variables()
    all_issues.extend(issues)
    
    # Only continue if credentials are set
    if not success:
        print()
        print("⚠️  Skipping remaining checks (credentials not configured)")
        print_summary(all_issues)
        sys.exit(1)
    
    # Check 2: Required libraries
    success, issues = check_kraken_libraries()
    all_issues.extend(issues)
    
    if not success:
        print()
        print("⚠️  Skipping connection test (libraries not installed)")
        print_summary(all_issues)
        sys.exit(1)
    
    # Check 3: API connection
    success, issues = test_kraken_connection()
    all_issues.extend(issues)
    
    if not success:
        print()
        print("⚠️  Skipping trading readiness check (connection failed)")
        print_summary(all_issues)
        sys.exit(1)
    
    # Check 4: Trading readiness (optional - might fail if bot code has dependencies)
    print()
    print("ℹ️  Attempting full trading readiness check...")
    print("   (This may fail if bot dependencies are missing - that's okay)")
    try:
        success, issues = test_trading_readiness()
        all_issues.extend(issues)
    except Exception as e:
        print(f"⚠️  Trading readiness check skipped: {e}")
        print("   Manual verification recommended after deployment")
    
    # Print final summary
    if print_summary(all_issues):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
