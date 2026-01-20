#!/usr/bin/env python3
"""
Quick Start Kraken User Trading - Daivon & Tania

This script provides a quick way to enable and verify Kraken trading
for Daivon Frazier and Tania Gilbert.

Usage:
    python3 quick_start_kraken_users.py [--check-only]

Options:
    --check-only    Only check status, don't modify anything
"""

import os
import sys
import json
from pathlib import Path

def print_banner():
    """Print script banner"""
    print()
    print("=" * 80)
    print("    🚀 QUICK START: KRAKEN USER TRADING")
    print("    Users: Daivon Frazier & Tania Gilbert")
    print("=" * 80)
    print()

def check_user_config_files():
    """Verify user configuration files exist and are properly configured"""
    print("📋 Checking user configuration files...")
    print("-" * 80)
    
    config_dir = Path("config/users")
    
    # Check if config directory exists
    if not config_dir.exists():
        print(f"❌ Config directory not found: {config_dir}")
        return False
    
    # Check retail_kraken.json
    retail_kraken_file = config_dir / "retail_kraken.json"
    if not retail_kraken_file.exists():
        print(f"❌ Retail Kraken config not found: {retail_kraken_file}")
        return False
    
    # Load and verify users
    try:
        with open(retail_kraken_file, 'r') as f:
            users = json.load(f)
        
        print(f"✅ Found retail_kraken.json with {len(users)} users")
        
        # Check for Daivon
        daivon = next((u for u in users if u.get('user_id') == 'daivon_frazier'), None)
        if daivon:
            enabled = daivon.get('enabled', False)
            status = "✅ ENABLED" if enabled else "❌ DISABLED"
            print(f"   • Daivon Frazier: {status}")
        else:
            print(f"   ❌ Daivon Frazier: NOT FOUND in config")
        
        # Check for Tania
        tania = next((u for u in users if u.get('user_id') == 'tania_gilbert'), None)
        if tania:
            enabled = tania.get('enabled', False)
            status = "✅ ENABLED" if enabled else "❌ DISABLED"
            print(f"   • Tania Gilbert: {status}")
        else:
            print(f"   ❌ Tania Gilbert: NOT FOUND in config")
        
        print()
        # Check both users exist and are enabled
        return (daivon is not None and tania is not None and 
                daivon.get('enabled', False) and tania.get('enabled', False))
    
    except Exception as e:
        print(f"❌ Error reading config: {e}")
        print()
        return False

def check_credentials():
    """Check if Kraken credentials are set in environment"""
    print("🔑 Checking credentials...")
    print("-" * 80)
    
    # Try to load from .env files
    try:
        from dotenv import load_dotenv
        
        # Try locked credentials first
        if Path('.env.kraken_users_locked').exists():
            load_dotenv('.env.kraken_users_locked')
            print("✅ Loaded from .env.kraken_users_locked")
        elif Path('.env').exists():
            load_dotenv('.env')
            print("✅ Loaded from .env")
        else:
            print("⚠️  No .env files found, checking system environment")
    except ImportError:
        print("⚠️  python-dotenv not installed, checking system environment")
    
    # Check Daivon credentials
    daivon_key = os.getenv('KRAKEN_USER_DAIVON_API_KEY', '').strip()
    daivon_secret = os.getenv('KRAKEN_USER_DAIVON_API_SECRET', '').strip()
    
    if daivon_key and daivon_secret:
        print(f"✅ Daivon credentials: Key ({len(daivon_key)} chars), Secret ({len(daivon_secret)} chars)")
    else:
        print(f"❌ Daivon credentials: MISSING")
    
    # Check Tania credentials
    tania_key = os.getenv('KRAKEN_USER_TANIA_API_KEY', '').strip()
    tania_secret = os.getenv('KRAKEN_USER_TANIA_API_SECRET', '').strip()
    
    if tania_key and tania_secret:
        print(f"✅ Tania credentials: Key ({len(tania_key)} chars), Secret ({len(tania_secret)} chars)")
    else:
        print(f"❌ Tania credentials: MISSING")
    
    print()
    
    return (daivon_key and daivon_secret and tania_key and tania_secret)

def check_kraken_sdk():
    """Verify Kraken SDK is installed"""
    print("📦 Checking Kraken SDK...")
    print("-" * 80)
    
    try:
        import krakenex
        import pykrakenapi
        print("✅ Kraken SDK installed (krakenex + pykrakenapi)")
        print()
        return True
    except ImportError as e:
        print(f"❌ Kraken SDK not installed: {e}")
        print()
        print("   To install:")
        print("   pip install krakenex pykrakenapi")
        print()
        return False

def verify_trading_ready():
    """Run comprehensive checks to verify trading is ready"""
    print_banner()
    
    # Run all checks
    config_ok = check_user_config_files()
    creds_ok = check_credentials()
    sdk_ok = check_kraken_sdk()
    
    # Print summary
    print("=" * 80)
    print("    STATUS SUMMARY")
    print("=" * 80)
    print()
    
    if config_ok and creds_ok and sdk_ok:
        print("✅ ALL CHECKS PASSED")
        print()
        print("🚀 KRAKEN USER TRADING IS READY!")
        print()
        print("Next Steps:")
        print("   1. Deploy credentials to your platform (Railway/Render)")
        print("   2. Start the bot: ./start.sh")
        print("   3. Check logs for:")
        print("      '🚀 USER: Daivon Frazier: TRADING (Broker: KRAKEN)'")
        print("      '🚀 USER: Tania Gilbert: TRADING (Broker: KRAKEN)'")
        print()
        return True
    else:
        print("❌ SOME CHECKS FAILED")
        print()
        print("Issues Found:")
        if not config_ok:
            print("   ❌ User configuration issues")
            print("      → Verify config/users/retail_kraken.json")
        if not creds_ok:
            print("   ❌ Missing credentials")
            print("      → Set environment variables or create .env file")
            print("      → See KRAKEN_USERS_DEPLOYMENT_GUIDE.md")
        if not sdk_ok:
            print("   ❌ Kraken SDK not installed")
            print("      → Run: pip install krakenex pykrakenapi")
        print()
        print("See KRAKEN_USERS_DEPLOYMENT_GUIDE.md for detailed instructions")
        print()
        return False

def show_deployment_instructions():
    """Show quick deployment instructions"""
    print()
    print("=" * 80)
    print("    DEPLOYMENT INSTRUCTIONS")
    print("=" * 80)
    print()
    print("To deploy these locked credentials:")
    print()
    print("1. VALIDATE LOCALLY:")
    print("   python3 verify_kraken_user_credentials.py")
    print()
    print("2. DEPLOY TO RAILWAY:")
    print("   • Go to https://railway.app/dashboard")
    print("   • Add 4 environment variables from .env.kraken_users_locked")
    print("   • Railway auto-deploys")
    print()
    print("3. DEPLOY TO RENDER:")
    print("   • Go to https://dashboard.render.com")
    print("   • Add 4 environment variables")
    print("   • Click 'Manual Deploy'")
    print()
    print("4. VERIFY:")
    print("   • Check logs for 'USER: [Name]: TRADING (Broker: KRAKEN)'")
    print()
    print("📖 Full Guide: KRAKEN_USERS_DEPLOYMENT_GUIDE.md")
    print()

def main():
    """Main entry point"""
    check_only = '--check-only' in sys.argv
    
    # Run verification
    ready = verify_trading_ready()
    
    # Show deployment instructions
    if ready:
        show_deployment_instructions()
        return 0
    else:
        return 1

if __name__ == "__main__":
    sys.exit(main())
