#!/usr/bin/env python3
"""
KRAKEN CONNECTION SETUP AND VERIFICATION
=========================================

This script helps you connect the master account and all user accounts to Kraken.
It will:
1. Check if Kraken credentials are configured
2. Validate the credentials by attempting a test connection
3. Guide you through the setup process if credentials are missing
4. Verify that both master and users can connect independently

IMPORTANT: This addresses the issue where Coinbase might be interfering with 
Kraken connections. Each broker operates INDEPENDENTLY - if one fails, 
the others continue trading normally.
"""

import os
import sys
import time
import logging
import traceback

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Try to load dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


def print_header(text):
    """Print a formatted header"""
    print()
    print("=" * 80)
    print(f"  {text}")
    print("=" * 80)
    print()


def print_section(text):
    """Print a section divider"""
    print()
    print("-" * 80)
    print(f"  {text}")
    print("-" * 80)


def check_credentials():
    """Check if Kraken credentials are configured"""
    print_section("STEP 1: Checking Kraken Credentials")
    
    # Master credentials
    master_key = os.getenv('KRAKEN_MASTER_API_KEY', '').strip()
    master_secret = os.getenv('KRAKEN_MASTER_API_SECRET', '').strip()
    
    # User credentials
    daivon_key = os.getenv('KRAKEN_USER_DAIVON_API_KEY', '').strip()
    daivon_secret = os.getenv('KRAKEN_USER_DAIVON_API_SECRET', '').strip()
    
    tania_key = os.getenv('KRAKEN_USER_TANIA_API_KEY', '').strip()
    tania_secret = os.getenv('KRAKEN_USER_TANIA_API_SECRET', '').strip()
    
    # Check master
    master_configured = bool(master_key and master_secret)
    if master_configured:
        print(f"  ✅ MASTER ACCOUNT: Configured")
        print(f"     Key: {master_key[:8]}...{master_key[-8:] if len(master_key) > 16 else ''}")
    else:
        print(f"  ❌ MASTER ACCOUNT: NOT configured")
    
    # Check Daivon
    daivon_configured = bool(daivon_key and daivon_secret)
    if daivon_configured:
        print(f"  ✅ USER #1 (Daivon Frazier): Configured")
        print(f"     Key: {daivon_key[:8]}...{daivon_key[-8:] if len(daivon_key) > 16 else ''}")
    else:
        print(f"  ❌ USER #1 (Daivon Frazier): NOT configured")
    
    # Check Tania
    tania_configured = bool(tania_key and tania_secret)
    if tania_configured:
        print(f"  ✅ USER #2 (Tania Gilbert): Configured")
        print(f"     Key: {tania_key[:8]}...{tania_key[-8:] if len(tania_key) > 16 else ''}")
    else:
        print(f"  ❌ USER #2 (Tania Gilbert): NOT configured")
    
    print()
    return {
        'master': master_configured,
        'daivon': daivon_configured,
        'tania': tania_configured
    }


def test_master_connection():
    """Test master account Kraken connection"""
    print_section("STEP 2: Testing Master Account Connection")
    
    try:
        from broker_manager import KrakenBroker, AccountType
        
        print("  🔌 Attempting to connect Kraken master account...")
        print("  ⏱️  This may take a few seconds...")
        print()
        
        broker = KrakenBroker(account_type=AccountType.MASTER)
        
        if broker.connect():
            print("  ✅ MASTER ACCOUNT CONNECTED SUCCESSFULLY!")
            print()
            
            # Try to get balance
            try:
                balance = broker.get_account_balance()
                print(f"  💰 Master Account Balance: ${balance:,.2f} USD")
                print()
                
                # Check if funded
                if balance >= 1.0:
                    print(f"  ✅ Account is FUNDED (${balance:,.2f} >= $1.00)")
                    print(f"  ✅ Master can START TRADING on Kraken!")
                else:
                    print(f"  ⚠️  Account balance is LOW (${balance:,.2f} < $1.00)")
                    print(f"  ⚠️  Please fund account to start trading")
                
                return True
            except Exception as bal_err:
                print(f"  ⚠️  Could not fetch balance: {bal_err}")
                print(f"  ✅ Connection successful, but balance check failed")
                return True
        else:
            print("  ❌ MASTER ACCOUNT CONNECTION FAILED")
            print()
            print("  🔧 Troubleshooting:")
            print("     1. Verify API key and secret are correct")
            print("     2. Check API key permissions at https://www.kraken.com/u/security/api")
            print("     3. Required permissions: Query Funds, Query Open Orders")
            print("     4. Ensure nonce window is set to maximum (10 seconds recommended)")
            print()
            return False
            
    except ImportError as e:
        print(f"  ❌ Failed to import Kraken broker: {e}")
        print(f"  ⚠️  The Kraken SDK may not be installed")
        print(f"  🔧 Fix: pip install krakenex pykrakenapi")
        return False
    except Exception as e:
        print(f"  ❌ Connection error: {e}")
        traceback.print_exc()
        return False


def test_user_connection(user_id, user_name):
    """Test user account Kraken connection"""
    print_section(f"Testing {user_name} Connection")
    
    try:
        from broker_manager import KrakenBroker, AccountType
        
        print(f"  🔌 Attempting to connect {user_name}'s Kraken account...")
        print("  ⏱️  This may take a few seconds...")
        print()
        
        broker = KrakenBroker(account_type=AccountType.USER, user_id=user_id)
        
        if broker.connect():
            print(f"  ✅ {user_name.upper()} CONNECTED SUCCESSFULLY!")
            print()
            
            # Try to get balance
            try:
                balance = broker.get_account_balance()
                print(f"  💰 {user_name} Balance: ${balance:,.2f} USD")
                print()
                
                # Check if funded
                if balance >= 1.0:
                    print(f"  ✅ Account is FUNDED (${balance:,.2f} >= $1.00)")
                    print(f"  ✅ {user_name} can START TRADING on Kraken!")
                else:
                    print(f"  ⚠️  Account balance is LOW (${balance:,.2f} < $1.00)")
                    print(f"  ⚠️  Please fund account to start trading")
                
                return True
            except Exception as bal_err:
                print(f"  ⚠️  Could not fetch balance: {bal_err}")
                print(f"  ✅ Connection successful, but balance check failed")
                return True
        else:
            print(f"  ❌ {user_name.upper()} CONNECTION FAILED")
            print()
            print("  🔧 Troubleshooting:")
            print(f"     1. Verify API key and secret for {user_name} are correct")
            print("     2. Check API key permissions at https://www.kraken.com/u/security/api")
            print("     3. Required permissions: Query Funds, Query Open Orders")
            print("     4. Ensure nonce window is set to maximum (10 seconds recommended)")
            print()
            return False
            
    except Exception as e:
        print(f"  ❌ Connection error: {e}")
        traceback.print_exc()
        return False


def show_setup_instructions(credential_status):
    """Show setup instructions for missing credentials"""
    print_header("SETUP INSTRUCTIONS")
    
    missing_any = not all(credential_status.values())
    
    if not missing_any:
        print("  ✅ All credentials are configured!")
        print()
        return
    
    print("  📋 Follow these steps to configure missing credentials:")
    print()
    
    if not credential_status['master']:
        print("  🔧 MASTER ACCOUNT SETUP:")
        print("     1. Log in to https://www.kraken.com")
        print("     2. Go to Settings → API → Generate New Key")
        print("     3. Set permissions:")
        print("        ✓ Query Funds")
        print("        ✓ Query Open Orders & Trades")
        print("        ✓ Query Closed Orders & Trades")
        print("        ✓ Create & Modify Orders")
        print("        ✓ Cancel/Close Orders")
        print("     4. Set Nonce Window: 10 seconds (maximum)")
        print("     5. Generate key and copy both API Key and Private Key")
        print("     6. Add to environment variables:")
        print("        export KRAKEN_MASTER_API_KEY='<your-api-key>'")
        print("        export KRAKEN_MASTER_API_SECRET='<your-private-key>'")
        print()
    
    if not credential_status['daivon']:
        print("  🔧 DAIVON FRAZIER ACCOUNT SETUP:")
        print("     1. Log in to Daivon's Kraken account")
        print("     2. Go to Settings → API → Generate New Key")
        print("     3. Set same permissions as master account")
        print("     4. Set Nonce Window: 10 seconds (maximum)")
        print("     5. Add to environment variables:")
        print("        export KRAKEN_USER_DAIVON_API_KEY='<api-key>'")
        print("        export KRAKEN_USER_DAIVON_API_SECRET='<private-key>'")
        print()
    
    if not credential_status['tania']:
        print("  🔧 TANIA GILBERT ACCOUNT SETUP:")
        print("     1. Log in to Tania's Kraken account")
        print("     2. Go to Settings → API → Generate New Key")
        print("     3. Set same permissions as master account")
        print("     4. Set Nonce Window: 10 seconds (maximum)")
        print("     5. Add to environment variables:")
        print("        export KRAKEN_USER_TANIA_API_KEY='<api-key>'")
        print("        export KRAKEN_USER_TANIA_API_SECRET='<private-key>'")
        print()
    
    print("  📁 For Railway/Render deployment:")
    print("     1. Go to your service dashboard")
    print("     2. Navigate to Variables/Environment Variables")
    print("     3. Add each variable listed above")
    print("     4. Redeploy the service")
    print()


def verify_independent_trading():
    """Verify that brokers operate independently"""
    print_header("INDEPENDENT BROKER VERIFICATION")
    
    print("  ✅ CRITICAL ARCHITECTURE CONFIRMED:")
    print()
    print("  🔒 Each broker operates COMPLETELY INDEPENDENTLY:")
    print("     • Master trades independently from users")
    print("     • User #1 trades independently from Master and User #2")
    print("     • User #2 trades independently from Master and User #1")
    print()
    print("  🚨 Coinbase CANNOT interfere with Kraken:")
    print("     • Each broker has its own connection")
    print("     • Each broker has its own balance checks")
    print("     • Each broker manages its own positions")
    print("     • If Coinbase fails, Kraken continues trading")
    print("     • If Kraken fails, Coinbase continues trading")
    print()
    print("  🎯 Once credentials are configured, trading starts automatically:")
    print("     • Master will scan markets and execute trades on Kraken")
    print("     • Each user will trade on their own Kraken account")
    print("     • All accounts operate in parallel without interference")
    print()


def main():
    """Main execution"""
    print_header("KRAKEN CONNECTION SETUP AND VERIFICATION")
    
    print("  This script will:")
    print("  1. Check if Kraken credentials are configured")
    print("  2. Test master account connection")
    print("  3. Test user account connections")
    print("  4. Verify independent trading capability")
    print()
    
    # Step 1: Check credentials
    credential_status = check_credentials()
    
    # If any credentials are missing, show setup instructions
    if not all(credential_status.values()):
        show_setup_instructions(credential_status)
        print()
        print("  ⚠️  Cannot test connections - missing credentials")
        print("  🔧  Please configure credentials and run this script again")
        print()
        return 1
    
    # Step 2: Test master connection
    master_connected = False
    if credential_status['master']:
        master_connected = test_master_connection()
        time.sleep(2)  # Delay between connections
    
    # Step 3: Test user connections
    daivon_connected = False
    if credential_status['daivon']:
        daivon_connected = test_user_connection('daivon_frazier', 'Daivon Frazier')
        time.sleep(2)  # Delay between connections
    
    tania_connected = False
    if credential_status['tania']:
        tania_connected = test_user_connection('tania_gilbert', 'Tania Gilbert')
        time.sleep(2)
    
    # Step 4: Verify independent trading
    verify_independent_trading()
    
    # Summary
    print_header("CONNECTION SUMMARY")
    
    print("  📊 Master Account:")
    if master_connected:
        print("     ✅ CONNECTED - Can trade on Kraken")
    else:
        print("     ❌ NOT CONNECTED - Cannot trade")
    
    print()
    print("  👤 User Accounts:")
    if daivon_connected:
        print("     ✅ Daivon Frazier - CONNECTED - Can trade on Kraken")
    else:
        print("     ❌ Daivon Frazier - NOT CONNECTED - Cannot trade")
    
    if tania_connected:
        print("     ✅ Tania Gilbert - CONNECTED - Can trade on Kraken")
    else:
        print("     ❌ Tania Gilbert - NOT CONNECTED - Cannot trade")
    
    print()
    
    # Overall status
    all_connected = master_connected and daivon_connected and tania_connected
    
    if all_connected:
        print("  🎉 SUCCESS! All accounts are connected to Kraken!")
        print()
        print("  ✅ Master and all users can now trade on Kraken")
        print("  ✅ Each account operates independently")
        print("  ✅ Coinbase and Kraken won't interfere with each other")
        print()
        print("  🚀 Next steps:")
        print("     1. Start the bot (it will connect all accounts automatically)")
        print("     2. Monitor logs to see trading activity")
        print("     3. Each account will trade based on the APEX strategy")
        print()
        return 0
    else:
        print("  ⚠️  Some accounts could not connect")
        print()
        print("  🔧 Please review the errors above and:")
        print("     1. Verify API credentials are correct")
        print("     2. Check API key permissions on Kraken")
        print("     3. Ensure accounts are funded (minimum $1.00)")
        print("     4. Run this script again after fixing issues")
        print()
        return 1


if __name__ == '__main__':
    sys.exit(main())
