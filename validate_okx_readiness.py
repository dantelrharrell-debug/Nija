#!/usr/bin/env python3
"""
OKX Trading Readiness Validator

Quick script to verify OKX integration is ready for trading.
This checks:
1. OKX SDK is installed
2. OKX is enabled in configuration
3. OKX broker classes can be imported
4. BrokerFactory can create OKX instances

Usage:
    python validate_okx_readiness.py
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def print_header(text):
    """Print formatted header"""
    print("\n" + "="*70)
    print(f"  {text}")
    print("="*70)

def print_status(item, status, details=""):
    """Print status line"""
    status_icon = "✅" if status else "❌"
    print(f"{status_icon} {item}: {'PASS' if status else 'FAIL'}")
    if details:
        print(f"   → {details}")

def main():
    """Run all validation checks"""
    print("\n" + "🔥"*35)
    print("   OKX TRADING READINESS VALIDATOR")
    print("🔥"*35)
    
    all_passed = True
    
    # Check 1: OKX SDK installed
    print_header("CHECK 1: OKX SDK Installation")
    try:
        import okx
        print_status("OKX SDK", True, f"Version: {okx.__version__ if hasattr(okx, '__version__') else 'Installed'}")
    except ImportError as e:
        print_status("OKX SDK", False, f"Not installed. Run: pip install okx")
        all_passed = False
    
    # Check 2: OKX in apex_config
    print_header("CHECK 2: Configuration Status")
    try:
        from apex_config import BROKERS, BROKER_CONFIG
        
        # Check if OKX is in supported list
        okx_supported = 'okx' in BROKERS.get('supported', [])
        print_status("OKX in supported brokers", okx_supported, 
                    f"Supported: {BROKERS.get('supported', [])}")
        
        # Check if OKX is enabled
        okx_enabled = BROKERS.get('okx', {}).get('enabled', False)
        print_status("OKX enabled in config", okx_enabled,
                    "bot/apex_config.py line 276" if okx_enabled else 
                    "Set 'enabled': True in bot/apex_config.py line 276")
        
        # Check if OKX has broker config
        okx_has_config = 'okx' in BROKER_CONFIG
        print_status("OKX broker configuration", okx_has_config,
                    f"Settings: {BROKER_CONFIG.get('okx', {})}" if okx_has_config else "Missing")
        
        if not (okx_supported and okx_enabled and okx_has_config):
            all_passed = False
            
    except ImportError as e:
        print_status("Configuration import", False, f"Error: {e}")
        all_passed = False
    
    # Check 3: OKXBroker class
    print_header("CHECK 3: OKXBroker Class (broker_manager.py)")
    try:
        from broker_manager import OKXBroker
        
        # Check if class exists
        print_status("OKXBroker class", True, "Found in broker_manager.py")
        
        # Check key methods
        has_connect = hasattr(OKXBroker, 'connect')
        print_status("connect() method", has_connect)
        
        has_balance = hasattr(OKXBroker, 'get_account_balance')
        print_status("get_account_balance() method", has_balance)
        
        has_market_data = hasattr(OKXBroker, 'get_candles')
        print_status("get_candles() method", has_market_data)
        
        has_place_order = hasattr(OKXBroker, 'place_market_order')
        print_status("place_market_order() method", has_place_order)
        
        if not all([has_connect, has_balance, has_market_data, has_place_order]):
            all_passed = False
            
    except ImportError as e:
        print_status("OKXBroker import", False, f"Error: {e}")
        all_passed = False
    
    # Check 4: OKXBrokerAdapter class
    print_header("CHECK 4: OKXBrokerAdapter Class (broker_integration.py)")
    try:
        from broker_integration import BrokerFactory
        
        # Try to create OKX broker
        okx_broker = BrokerFactory.create_broker('okx')
        print_status("BrokerFactory.create_broker('okx')", True, 
                    f"Type: {type(okx_broker).__name__}")
        
        # Check if it implements BrokerInterface
        has_connect = hasattr(okx_broker, 'connect')
        print_status("Implements BrokerInterface", has_connect)
        
    except Exception as e:
        print_status("BrokerFactory OKX creation", False, f"Error: {e}")
        all_passed = False
    
    # Check 5: Environment template
    print_header("CHECK 5: Environment Configuration")
    env_example_exists = os.path.exists('.env.example')
    print_status(".env.example file", env_example_exists)
    
    if env_example_exists:
        with open('.env.example', 'r') as f:
            content = f.read()
            has_okx_key = 'OKX_API_KEY' in content
            has_okx_secret = 'OKX_API_SECRET' in content
            has_okx_pass = 'OKX_PASSPHRASE' in content
            has_okx_testnet = 'OKX_USE_TESTNET' in content
            
            print_status("OKX_API_KEY template", has_okx_key)
            print_status("OKX_API_SECRET template", has_okx_secret)
            print_status("OKX_PASSPHRASE template", has_okx_pass)
            print_status("OKX_USE_TESTNET template", has_okx_testnet)
            
            if not all([has_okx_key, has_okx_secret, has_okx_pass, has_okx_testnet]):
                all_passed = False
    else:
        print_status(".env.example content", False, "File not found")
        all_passed = False
    
    # Check 6: Documentation
    print_header("CHECK 6: Documentation")
    docs = {
        'OKX_SETUP_GUIDE.md': 'Complete setup guide',
        'OKX_QUICK_REFERENCE.md': 'Quick reference card',
        'OKX_INTEGRATION_COMPLETE.md': 'Implementation summary',
        'OKX_TRADING_READINESS_STATUS.md': 'Readiness status',
        'OKX_DOCUMENTATION_INDEX.md': 'Documentation index',
        'test_okx_connection.py': 'Test script'
    }
    
    for doc, description in docs.items():
        exists = os.path.exists(doc)
        print_status(f"{doc}", exists, description)
        if not exists:
            all_passed = False
    
    # Final summary
    print_header("FINAL VERDICT")
    
    if all_passed:
        print("\n🎉 " + "="*66 + " 🎉")
        print("   ✅ OKX IS FULLY READY FOR TRADING!")
        print("="*70 + "\n")
        print("📋 What you have:")
        print("   ✅ OKX SDK installed")
        print("   ✅ OKX enabled in configuration")
        print("   ✅ OKXBroker class implemented")
        print("   ✅ OKXBrokerAdapter implemented")
        print("   ✅ BrokerFactory support")
        print("   ✅ Environment template")
        print("   ✅ Complete documentation")
        print("\n📝 What you need to do:")
        print("   1. Get OKX API credentials (https://www.okx.com/account/my-api)")
        print("   2. Add credentials to .env file")
        print("   3. Run: python test_okx_connection.py")
        print("   4. Start trading!")
        print("\n📚 Documentation:")
        print("   • Quick Start: OKX_QUICK_REFERENCE.md")
        print("   • Full Setup: OKX_SETUP_GUIDE.md")
        print("   • Status: OKX_TRADING_READINESS_STATUS.md")
        print("\n⚡ Quick test:")
        print("   python test_okx_connection.py")
        print("\n" + "="*70)
    else:
        print("\n❌ " + "="*66 + " ❌")
        print("   ⚠️  SOME CHECKS FAILED")
        print("="*70 + "\n")
        print("Please review the failed checks above and fix them.")
        print("\nCommon fixes:")
        print("   • Install OKX SDK: pip install okx")
        print("   • Enable OKX in bot/apex_config.py (line 276)")
        print("   • Check that all files are present")
        print("\n" + "="*70)
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
