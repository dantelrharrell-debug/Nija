#!/usr/bin/env python3
"""
Quick Setup Script for Kraken Users (Daivon & Tania)
Guides the user through getting Kraken connected step-by-step.
"""

import os
import sys

def print_header(text):
    """Print a formatted header."""
    print()
    print("=" * 80)
    print(f"  {text}")
    print("=" * 80)
    print()

def print_step(number, title):
    """Print a step header."""
    print()
    print(f"📍 STEP {number}: {title}")
    print("-" * 80)

def check_credentials():
    """Check which credentials are set."""
    creds = {
        "KRAKEN_MASTER_API_KEY": os.getenv("KRAKEN_MASTER_API_KEY"),
        "KRAKEN_MASTER_API_SECRET": os.getenv("KRAKEN_MASTER_API_SECRET"),
        "KRAKEN_USER_DAIVON_API_KEY": os.getenv("KRAKEN_USER_DAIVON_API_KEY"),
        "KRAKEN_USER_DAIVON_API_SECRET": os.getenv("KRAKEN_USER_DAIVON_API_SECRET"),
        "KRAKEN_USER_TANIA_API_KEY": os.getenv("KRAKEN_USER_TANIA_API_KEY"),
        "KRAKEN_USER_TANIA_API_SECRET": os.getenv("KRAKEN_USER_TANIA_API_SECRET"),
    }
    
    set_count = sum(1 for v in creds.values() if v and v.strip())
    return set_count, creds

def main():
    print_header("QUICK SETUP: Get Daivon & Tania Trading on Kraken")
    
    # Check current status
    set_count, creds = check_credentials()
    
    print(f"Current status: {set_count}/6 credentials configured")
    print()
    
    if set_count == 6:
        print("✅ ALL CREDENTIALS ARE CONFIGURED!")
        print()
        print("Your Kraken accounts should be trading now.")
        print("Check your deployment logs to verify connections.")
        print()
        print("Verification commands:")
        print("  python3 test_kraken_users.py")
        print("  python3 display_broker_status.py")
        return 0
    
    print("⚠️  Missing credentials detected. Let's fix this!")
    print()
    
    # Show missing credentials
    print("Missing credentials:")
    for key, value in creds.items():
        if not value or not value.strip():
            account = key.replace("KRAKEN_", "").replace("_API_KEY", "").replace("_API_SECRET", "")
            if "SECRET" in key:
                print(f"  ❌ {key} (Private Key for {account})")
            else:
                print(f"  ❌ {key} (API Key for {account})")
    print()
    
    # Step-by-step guide
    print_step(1, "Get API Keys from Kraken (15 minutes)")
    print()
    print("You need to create API keys for 3 Kraken accounts:")
    print("  1. Master account")
    print("  2. Daivon's account")
    print("  3. Tania's account")
    print()
    print("For EACH account:")
    print("  a) Log in to https://www.kraken.com")
    print("  b) Go to Settings → API → Generate New Key")
    print("  c) Description: 'NIJA Trading Bot - [Account Name]'")
    print("  d) Enable these permissions:")
    print("     ✅ Query Funds")
    print("     ✅ Query Open Orders & Trades")
    print("     ✅ Query Closed Orders & Trades")
    print("     ✅ Create & Modify Orders")
    print("     ✅ Cancel/Close Orders")
    print("     ❌ DO NOT enable 'Withdraw Funds'")
    print("  e) Click 'Generate Key'")
    print("  f) SAVE BOTH the API Key and Private Key (Private Key shown ONLY ONCE!)")
    print()
    print("⚠️  IMPORTANT: Each account needs its own Kraken login and API key.")
    print()
    
    print_step(2, "Add Credentials to Your Deployment (3 minutes)")
    print()
    print("Choose your deployment platform:")
    print()
    print("▶ For Railway:")
    print("  1. Go to https://railway.app/dashboard")
    print("  2. Select your NIJA project → Click your service")
    print("  3. Click 'Variables' tab → Click 'New Variable'")
    print("  4. Add each of these 6 variables:")
    print()
    print("     Variable Name: KRAKEN_MASTER_API_KEY")
    print("     Value: [paste Master API Key]")
    print()
    print("     Variable Name: KRAKEN_MASTER_API_SECRET")
    print("     Value: [paste Master Private Key]")
    print()
    print("     Variable Name: KRAKEN_USER_DAIVON_API_KEY")
    print("     Value: [paste Daivon's API Key]")
    print()
    print("     Variable Name: KRAKEN_USER_DAIVON_API_SECRET")
    print("     Value: [paste Daivon's Private Key]")
    print()
    print("     Variable Name: KRAKEN_USER_TANIA_API_KEY")
    print("     Value: [paste Tania's API Key]")
    print()
    print("     Variable Name: KRAKEN_USER_TANIA_API_SECRET")
    print("     Value: [paste Tania's Private Key]")
    print()
    print("  5. Railway will auto-restart (takes ~2 minutes)")
    print()
    print("▶ For Render:")
    print("  1. Go to https://dashboard.render.com")
    print("  2. Select your NIJA service")
    print("  3. Click 'Environment' tab")
    print("  4. Click 'Add Environment Variable' for each of the 6 variables above")
    print("  5. Click 'Save Changes'")
    print("  6. Click 'Manual Deploy' → 'Deploy latest commit'")
    print()
    
    print_step(3, "Verify Connections (2 minutes)")
    print()
    print("After deployment restarts:")
    print()
    print("  1. Check your deployment logs")
    print("  2. Look for these success messages:")
    print()
    print("     ✅ Kraken MASTER credentials detected")
    print("     ✅ Kraken User #1 (Daivon) credentials detected")
    print("     ✅ Kraken User #2 (Tania) credentials detected")
    print("     ✅ MASTER: TRADING (Broker: KRAKEN)")
    print("     ✅ USER: Daivon Frazier: TRADING (Broker: KRAKEN)")
    print("     ✅ USER: Tania Gilbert: TRADING (Broker: KRAKEN)")
    print()
    print("  3. Run verification commands:")
    print()
    print("     python3 check_kraken_credentials.py")
    print("     python3 test_kraken_users.py")
    print("     python3 display_broker_status.py")
    print()
    
    print_header("TIMELINE")
    print("  • Get API keys (3 accounts × 5 min): 15 minutes")
    print("  • Add to deployment platform: 3 minutes")
    print("  • Deployment restart: 2 minutes (automatic)")
    print("  • Verify connections: 2 minutes")
    print()
    print("  TOTAL TIME: ~20 minutes")
    print()
    
    print_header("TROUBLESHOOTING")
    print("If you encounter issues:")
    print()
    print("  • 'Permission denied' → Check all 5 permissions are enabled on Kraken")
    print("  • 'Invalid key' → Verify you copied the complete key with no spaces")
    print("  • 'Invalid nonce' → Each account must have its own unique API key")
    print("  • Still not working → Run: python3 diagnose_kraken_status.py")
    print()
    print("📖 Complete guide: KRAKEN_USER_SETUP_SOLUTION_JAN_18_2026.md")
    print()
    
    print("=" * 80)
    print()
    
    return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
