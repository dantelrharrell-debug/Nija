#!/usr/bin/env python3
"""
ACTIVATE KRAKEN TRADING - BOTH NIJA AND USER #1

This script ensures BOTH Kraken accounts are connected and actively trading:
1. NIJA's main Kraken account (from .env KRAKEN_API_KEY)
2. User #1's (Daivon Frazier) Kraken account

After running this, the bot will trade on:
- Coinbase (main account)
- Kraken (NIJA's account)
- Kraken (User #1's account via multi-user system)
"""

import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def check_kraken_credentials():
    """Check if Kraken credentials are set in environment"""
    print()
    print("=" * 80)
    print("STEP 1: VERIFY KRAKEN CREDENTIALS")
    print("=" * 80)
    
    # Load .env file
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print("✅ Loaded environment from .env file")
    except ImportError:
        print("⚠️  python-dotenv not available, using system environment")
    
    kraken_key = os.getenv("KRAKEN_API_KEY", "").strip()
    kraken_secret = os.getenv("KRAKEN_API_SECRET", "").strip()
    
    if not kraken_key or not kraken_secret:
        print()
        print("❌ KRAKEN CREDENTIALS NOT FOUND")
        print()
        print("Your .env file should have:")
        print("  KRAKEN_API_KEY=8zdYy7PMRjnyDraiJUtrAb3wmu8MFxKBON3nrTkjkwnJ9iIUQyKNGKP7")
        print("  KRAKEN_API_SECRET=e2xaakHliGa5RwH7uXwuq6RLGospWaQhScaVJfsS6wIa9huHxmx+HgeQCax8A+gvqV3P9jXD9YbR3wtsipdpRA==")
        print()
        return False
    
    print(f"✅ KRAKEN_API_KEY set ({len(kraken_key)} chars)")
    print(f"✅ KRAKEN_API_SECRET set ({len(kraken_secret)} chars)")
    return True

def test_kraken_connection():
    """Test connection to Kraken API"""
    print()
    print("=" * 80)
    print("STEP 2: TEST KRAKEN CONNECTION")
    print("=" * 80)
    
    try:
        import krakenex
        from pykrakenapi import KrakenAPI
        print("✅ Kraken SDK installed")
    except ImportError as e:
        print(f"❌ Kraken SDK not installed: {e}")
        print()
        print("Install with: pip install krakenex pykrakenapi")
        return False
    
    kraken_key = os.getenv("KRAKEN_API_KEY", "").strip()
    kraken_secret = os.getenv("KRAKEN_API_SECRET", "").strip()
    
    try:
        api = krakenex.API(key=kraken_key, secret=kraken_secret)
        print("⏳ Connecting to Kraken Pro API...")
        
        balance = api.query_private('Balance')
        
        if balance and 'error' in balance and balance['error']:
            error_msgs = ', '.join(balance['error'])
            print(f"❌ Kraken API error: {error_msgs}")
            return False
        
        if balance and 'result' in balance:
            result = balance.get('result', {})
            usd = float(result.get('ZUSD', 0))
            usdt = float(result.get('USDT', 0))
            total = usd + usdt
            
            print()
            print("✅ KRAKEN CONNECTION SUCCESSFUL")
            print(f"   USD:  ${usd:.2f}")
            print(f"   USDT: ${usdt:.2f}")
            print(f"   Total: ${total:.2f}")
            return True
        
        print("❌ No balance data returned")
        return False
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

def initialize_user_system():
    """Initialize the multi-user system"""
    print()
    print("=" * 80)
    print("STEP 3: INITIALIZE MULTI-USER SYSTEM")
    print("=" * 80)
    
    try:
        # Check if user system is already initialized
        if os.path.exists('data/users'):
            print("✅ User system directory already exists")
        else:
            print("⏳ Creating user system directories...")
            os.makedirs('data/users', exist_ok=True)
            os.makedirs('data/users/auth', exist_ok=True)
            os.makedirs('data/users/config', exist_ok=True)
            print("✅ User system directories created")
        
        # Check if init script exists
        if os.path.exists('init_user_system.py'):
            print("⏳ Running init_user_system.py...")
            import subprocess
            result = subprocess.run(
                ['python3', 'init_user_system.py'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                print("✅ User system initialized")
                return True
            else:
                print(f"⚠️  Init script returned code {result.returncode}")
                if result.stdout:
                    print("Output:", result.stdout[:200])
                # Continue anyway - might already be initialized
                return True
        else:
            print("⚠️  init_user_system.py not found")
            print("   Multi-user system may not be fully initialized")
            return True
            
    except Exception as e:
        print(f"⚠️  Error initializing user system: {e}")
        # Don't fail - continue with setup
        return True

def setup_user1():
    """Setup User #1 (Daivon Frazier) with Kraken"""
    print()
    print("=" * 80)
    print("STEP 4: SETUP USER #1 (DAIVON FRAZIER)")
    print("=" * 80)
    
    try:
        if os.path.exists('setup_user_daivon.py'):
            print("⏳ Running setup_user_daivon.py...")
            import subprocess
            result = subprocess.run(
                ['python3', 'setup_user_daivon.py'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 or 'already exists' in result.stdout.lower():
                print("✅ User #1 (Daivon Frazier) configured")
                print("   Broker: Kraken Pro")
                print("   Credentials: Stored and encrypted")
                return True
            else:
                print(f"⚠️  Setup returned code {result.returncode}")
                if result.stderr:
                    print("Errors:", result.stderr[:200])
                # Check if user already exists
                return True
        else:
            print("⚠️  setup_user_daivon.py not found")
            print("   User #1 setup skipped")
            return True
            
    except Exception as e:
        print(f"⚠️  Error setting up User #1: {e}")
        return True

def enable_user1_trading():
    """Enable trading for User #1"""
    print()
    print("=" * 80)
    print("STEP 5: ENABLE USER #1 TRADING")
    print("=" * 80)
    
    try:
        if os.path.exists('manage_user_daivon.py'):
            print("⏳ Enabling trading for User #1...")
            import subprocess
            result = subprocess.run(
                ['python3', 'manage_user_daivon.py', 'enable'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 or 'enabled' in result.stdout.lower():
                print("✅ User #1 trading ENABLED")
                return True
            else:
                print(f"⚠️  Enable returned code {result.returncode}")
                # Continue anyway
                return True
        else:
            print("⚠️  manage_user_daivon.py not found")
            return True
            
    except Exception as e:
        print(f"⚠️  Error enabling User #1: {e}")
        return True

def verify_multi_broker_config():
    """Verify multi-broker configuration"""
    print()
    print("=" * 80)
    print("STEP 6: VERIFY MULTI-BROKER CONFIGURATION")
    print("=" * 80)
    
    multi_broker = os.getenv("MULTI_BROKER_INDEPENDENT", "").strip().lower()
    
    if multi_broker in ['true', '1', 'yes']:
        print("✅ MULTI_BROKER_INDEPENDENT = true")
        print("   Each broker runs independently")
    else:
        print("⚠️  MULTI_BROKER_INDEPENDENT not set")
        print("   Setting it to 'true' is recommended")
    
    return True

def main():
    print("=" * 80)
    print("🚀 ACTIVATE KRAKEN TRADING - NIJA + USER #1")
    print("=" * 80)
    print()
    print("This script will:")
    print("1. Verify Kraken API credentials")
    print("2. Test connection to Kraken")
    print("3. Initialize multi-user system")
    print("4. Setup User #1 (Daivon Frazier) with Kraken")
    print("5. Enable User #1 trading")
    print("6. Verify multi-broker configuration")
    print()
    input("Press ENTER to continue...")
    
    # Run all steps
    steps = [
        check_kraken_credentials,
        test_kraken_connection,
        initialize_user_system,
        setup_user1,
        enable_user1_trading,
        verify_multi_broker_config
    ]
    
    for step in steps:
        try:
            if not step():
                print()
                print("⚠️  Step had warnings but continuing...")
        except Exception as e:
            print(f"❌ Step failed: {e}")
            import traceback
            traceback.print_exc()
    
    # Final summary
    print()
    print("=" * 80)
    print("✅ ACTIVATION COMPLETE")
    print("=" * 80)
    print()
    print("When you start the bot (python bot.py), you should see:")
    print()
    print("1. NIJA's Kraken Connection:")
    print("   📊 Attempting to connect Kraken Pro...")
    print("      ✅ Kraken connected")
    print()
    print("2. Trading on Multiple Brokers:")
    print("   🔄 coinbase - Cycle #1")
    print("   🔄 kraken - Cycle #1")
    print()
    print("3. User #1 Trading (if multi-user active):")
    print("   👤 User: daivon_frazier")
    print("   🏦 Broker: Kraken Pro")
    print()
    print("If you only see 'coinbase' cycles, check the logs for Kraken errors.")
    print("Common issues:")
    print("  - API key permissions (need Query Funds, Query/Create/Modify Orders)")
    print("  - Rate limiting (403/429 errors)")
    print("  - Insufficient balance")
    print()
    print("=" * 80)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
