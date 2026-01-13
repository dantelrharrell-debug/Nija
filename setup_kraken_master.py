#!/usr/bin/env python3
"""
Quick Setup Guide for Kraken Master Account
=============================================

This script helps you configure the missing KRAKEN MASTER credentials.

Your current status:
  ✅ KRAKEN User #1 (Daivon): Configured
  ✅ KRAKEN User #2 (Tania): Configured
  ✅ OKX Master: Configured
  ❌ KRAKEN Master: NOT configured <- YOU ARE HERE

This script will guide you through adding the master Kraken credentials.

Usage:
    python3 setup_kraken_master.py
"""

import os
import sys


def print_banner():
    """Print welcome banner"""
    print()
    print("=" * 80)
    print("KRAKEN MASTER ACCOUNT SETUP".center(80))
    print("=" * 80)
    print()


def print_section(title):
    """Print section header"""
    print()
    print("─" * 80)
    print(f"  {title}")
    print("─" * 80)
    print()


def check_current_status():
    """Check what's already configured"""
    print_section("📊 CURRENT STATUS CHECK")
    
    # Check master
    master_key = os.getenv("KRAKEN_MASTER_API_KEY", "").strip()
    master_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "").strip()
    
    # Check users
    daivon_key = os.getenv("KRAKEN_USER_DAIVON_API_KEY", "").strip()
    daivon_secret = os.getenv("KRAKEN_USER_DAIVON_API_SECRET", "").strip()
    
    tania_key = os.getenv("KRAKEN_USER_TANIA_API_KEY", "").strip()
    tania_secret = os.getenv("KRAKEN_USER_TANIA_API_SECRET", "").strip()
    
    # Check OKX for comparison
    okx_key = os.getenv("OKX_API_KEY", "").strip()
    okx_secret = os.getenv("OKX_API_SECRET", "").strip()
    okx_pass = os.getenv("OKX_PASSPHRASE", "").strip()
    
    # Display status
    print("   📊 KRAKEN (Master):")
    if master_key and master_secret:
        print(f"      ✅ Configured (Key: {len(master_key)} chars, Secret: {len(master_secret)} chars)")
        master_configured = True
    else:
        print("      ❌ Not configured")
        master_configured = False
    
    print("   👤 KRAKEN (User #1: Daivon):")
    if daivon_key and daivon_secret:
        print(f"      ✅ Configured (Key: {len(daivon_key)} chars, Secret: {len(daivon_secret)} chars)")
    else:
        print("      ❌ Not configured")
    
    print("   👤 KRAKEN (User #2: Tania):")
    if tania_key and tania_secret:
        print(f"      ✅ Configured (Key: {len(tania_key)} chars, Secret: {len(tania_secret)} chars)")
    else:
        print("      ❌ Not configured")
    
    print("   📊 OKX (Master):")
    if okx_key and okx_secret and okx_pass:
        print(f"      ✅ Configured (Key: {len(okx_key)} chars, Secret: {len(okx_secret)} chars)")
    else:
        print("      ❌ Not configured")
    
    print()
    
    return master_configured


def show_setup_instructions():
    """Show detailed setup instructions"""
    print_section("🔧 HOW TO ADD KRAKEN MASTER CREDENTIALS")
    
    print("""
You have TWO options depending on where your bot is deployed:

╔══════════════════════════════════════════════════════════════════════════════╗
║  OPTION 1: RAILWAY DEPLOYMENT                                                ║
╚══════════════════════════════════════════════════════════════════════════════╝

1. Open your browser and go to: https://railway.app/

2. Navigate to your NIJA project

3. Click on your service (the one running the bot)

4. Click on the "Variables" tab

5. Add these TWO new variables:

   Variable Name:  KRAKEN_MASTER_API_KEY
   Variable Value: [paste your Kraken API key here]
   
   Variable Name:  KRAKEN_MASTER_API_SECRET
   Variable Value: [paste your Kraken API secret here]

6. Railway will automatically restart your service

7. Wait 2-3 minutes for the service to restart

8. Check the logs - you should see:
   📊 KRAKEN (Master):
      ✅ Configured (Key: 56 chars, Secret: 88 chars)


╔══════════════════════════════════════════════════════════════════════════════╗
║  OPTION 2: RENDER DEPLOYMENT                                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝

1. Open your browser and go to: https://dashboard.render.com/

2. Select your NIJA web service

3. Click on the "Environment" tab (left sidebar)

4. Scroll down to "Environment Variables"

5. Add these TWO new variables:

   Key:   KRAKEN_MASTER_API_KEY
   Value: [paste your Kraken API key here]
   
   Key:   KRAKEN_MASTER_API_SECRET
   Value: [paste your Kraken API secret here]

6. Click "Save Changes" button

7. Manually trigger a deploy:
   - Click "Manual Deploy" button (top right)
   - Select "Deploy latest commit"

8. Wait 3-5 minutes for deployment to complete

9. Check the logs - you should see:
   📊 KRAKEN (Master):
      ✅ Configured (Key: 56 chars, Secret: 88 chars)


╔══════════════════════════════════════════════════════════════════════════════╗
║  WHERE TO GET YOUR KRAKEN API CREDENTIALS                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝

If you don't have Kraken API credentials yet:

1. Log in to https://www.kraken.com

2. Go to: Settings → API → Create API Key

3. Set these permissions (REQUIRED for trading):
   ✅ Query Funds
   ✅ Query Open Orders & Trades
   ✅ Query Closed Orders & Trades
   ✅ Create & Modify Orders
   ✅ Cancel/Close Orders

4. Give it a name: "NIJA Master Trading Bot"

5. Click "Generate Key"

6. IMPORTANT: Copy BOTH the API Key and Private Key immediately
   ⚠️  You won't be able to see the Private Key again!

7. Store them securely (use a password manager)

8. Add them to Railway/Render using the instructions above


╔══════════════════════════════════════════════════════════════════════════════╗
║  SECURITY REMINDERS                                                          ║
╚══════════════════════════════════════════════════════════════════════════════╝

⚠️  NEVER share your API credentials publicly
⚠️  NEVER commit credentials to git repositories
⚠️  Use 2-Factor Authentication (2FA) on your Kraken account
⚠️  Set IP whitelist restrictions if possible
⚠️  Only enable permissions needed for trading
⚠️  Store credentials in a password manager
⚠️  Regularly rotate API keys (every 3-6 months)

""")


def show_verification_steps():
    """Show how to verify the setup worked"""
    print_section("✅ VERIFICATION STEPS")
    
    print("""
After adding the credentials and restarting:

1. Wait for deployment to complete (2-5 minutes)

2. Check the startup logs in Railway/Render

3. Look for this section in the logs:

   🔍 EXCHANGE CREDENTIAL STATUS:
   ────────────────────────────────────────────────────────
   📊 KRAKEN (Master):
      ✅ Configured (Key: 56 chars, Secret: 88 chars)    <- Should be ✅
   👤 KRAKEN (User #1: Daivon):
      ✅ Configured (Key: 56 chars, Secret: 88 chars)
   👤 KRAKEN (User #2: Tania):
      ✅ Configured (Key: 56 chars, Secret: 88 chars)
   ────────────────────────────────────────────────────────

4. Further in the logs, you should see:

   📊 Attempting to connect Kraken Pro (MASTER)...
      ✅ Connected to Kraken Pro API (MASTER)
      💰 Kraken balance: $X,XXX.XX

5. If you see ✅ for all three items, you're done! 🎉

6. If you see ❌ or connection errors, check:
   • Variable names are EXACTLY: KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET
   • No extra spaces before/after the values
   • API key has correct permissions
   • API key is not expired

""")


def show_quick_commands():
    """Show quick command references"""
    print_section("📋 QUICK REFERENCE COMMANDS")
    
    print("""
Local testing (if running locally):

    # Check status
    python3 check_kraken_status.py

    # Diagnose issues
    python3 diagnose_kraken_connection.py

    # Verify everything
    python3 diagnose_env_vars.py


Environment variable format (for reference):

    KRAKEN_MASTER_API_KEY=your-api-key-from-kraken
    KRAKEN_MASTER_API_SECRET=your-private-key-from-kraken


Typical API key format:

    API Key:     56 characters (letters + numbers)
    API Secret:  88 characters (base64 encoded)

""")


def main():
    """Main function"""
    print_banner()
    
    # Check current status
    is_configured = check_current_status()
    
    if is_configured:
        print("🎉 GREAT NEWS!")
        print()
        print("   Your Kraken Master account is ALREADY configured!")
        print("   You should be all set to trade on Kraken.")
        print()
        print("   If you're still having issues, run:")
        print("     python3 diagnose_kraken_connection.py")
        print()
        return 0
    
    # Show setup instructions
    show_setup_instructions()
    
    # Show verification
    show_verification_steps()
    
    # Show quick commands
    show_quick_commands()
    
    # Final message
    print_section("🚀 NEXT STEPS")
    print()
    print("   1. Go to Railway or Render (wherever your bot is deployed)")
    print("   2. Add the two environment variables:")
    print("      • KRAKEN_MASTER_API_KEY")
    print("      • KRAKEN_MASTER_API_SECRET")
    print("   3. Wait for automatic restart")
    print("   4. Check logs for ✅ confirmation")
    print()
    print("   That's it! Your bot will then trade on Kraken with the master account.")
    print()
    print("=" * 80)
    print()
    
    return 1


if __name__ == "__main__":
    sys.exit(main())
