#!/usr/bin/env python3
"""
VERIFY WHICH COINBASE ACCOUNT YOUR API KEYS ARE CONNECTED TO
This will show you exactly what the bot sees
"""

import os
import sys
import logging

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

logging.basicConfig(level=logging.INFO, format='%(message)s')

def main():
    print("\n" + "=" * 80)
    print("🔍 COINBASE API CONNECTION VERIFICATION")
    print("=" * 80)
    
    # Check credentials
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    
    print("\n1️⃣ Checking credentials...")
    if not api_key or not api_secret:
        print("   ❌ COINBASE_API_KEY or COINBASE_API_SECRET not found!")
        print("")
        print("   This script needs to run on Render (or with credentials set)")
        print("")
        print("   📋 TO RUN THIS CHECK:")
        print("   ─────────────────────────────────────────────────────────────")
        print("   Option A: Check Render Logs (EASIEST)")
        print("      1. Go to Render dashboard → NIJA service")
        print("      2. Click 'Manual Deploy' → 'Clear build cache & deploy'")
        print("      3. Watch the logs during startup")
        print("      4. Look for these sections:")
        print("         - '💰 BALANCE SUMMARY'")
        print("         - '📁 v3 Advanced Trade API'")
        print("         - '📊 ACCOUNT BALANCES'")
        print("")
        print("   Option B: Set credentials locally")
        print("      export COINBASE_API_KEY='your-key'")
        print("      export COINBASE_API_SECRET='your-pem-key'")
        print("      python3 VERIFY_API_CONNECTION.py")
        print("   ─────────────────────────────────────────────────────────────")
        print("")
        return
    
    print(f"   ✅ COINBASE_API_KEY: {api_key[:10]}...{api_key[-4:]}")
    print(f"   ✅ COINBASE_API_SECRET: Present ({len(api_secret)} chars)")
    
    # Initialize broker
    print("\n2️⃣ Connecting to Coinbase API...")
    from broker_manager import CoinbaseBroker
    
    broker = CoinbaseBroker()
    if not broker.connect():
        print("   ❌ Connection failed!")
        print("")
        print("   Possible issues:")
        print("      - Invalid API credentials")
        print("      - Expired API key")
        print("      - Network connection issue")
        print("")
        return
    
    print("   ✅ Connected successfully!")
    
    # Get account info
    print("\n3️⃣ Fetching account information...")
    print("")
    print("   This will show ALL accounts and balances that the API can see")
    print("   Watch for:")
    print("      • v2 Consumer accounts (NOT TRADABLE)")
    print("      • v3 Advanced Trade accounts (TRADABLE ✅)")
    print("")
    print("=" * 80)
    
    # Call get_account_balance which logs everything
    balance = broker.get_account_balance()
    
    print("=" * 80)
    print("\n4️⃣ Summary:")
    print("")
    
    trading_balance = balance.get('trading_balance', 0)
    consumer_usd = balance.get('consumer_usd', 0)
    consumer_usdc = balance.get('consumer_usdc', 0)
    
    if trading_balance >= 10:
        print("   ✅ SUCCESS! You have sufficient funds in Advanced Trade")
        print(f"      Trading balance: ${trading_balance:.2f}")
        print("")
        print("   🚀 The bot should start trading within 15-30 seconds!")
        print("")
    elif trading_balance > 0:
        print(f"   ⚠️  WARNING: Low balance in Advanced Trade (${trading_balance:.2f})")
        print("      Minimum recommended: $10.00")
        print("      Each trade needs ~$5.50 ($5.00 + fees)")
        print("")
    else:
        print("   ❌ PROBLEM: No funds in Advanced Trade portfolio")
        print("")
        
        if consumer_usd > 0 or consumer_usdc > 0:
            print(f"   💡 Found ${consumer_usd + consumer_usdc:.2f} in Consumer wallet")
            print("")
            print("   🔧 ACTION REQUIRED: Transfer to Advanced Trade")
            print("      1. Go to: https://www.coinbase.com/advanced-portfolio")
            print("      2. Click 'Deposit' → 'From Coinbase'")
            print(f"      3. Transfer ${consumer_usd + consumer_usdc:.2f} USD/USDC")
            print("      4. Wait 1-2 minutes")
            print("      5. Restart Render service")
            print("")
        else:
            print("   💡 No funds detected in ANY account")
            print("")
            print("   Possible causes:")
            print("      1. API keys are for a different Coinbase account")
            print("      2. Funds are in a different portfolio/vault")
            print("      3. No funds in the account at all")
            print("")
            print("   🔍 NEXT STEPS:")
            print("      1. Verify API keys match your funded account")
            print("      2. Check https://www.coinbase.com/settings/api")
            print("      3. Ensure the API key has 'trade' permissions")
            print("")
    
    # Show crypto holdings if any
    crypto = balance.get('crypto', {})
    if crypto:
        print("   🪙 Crypto holdings detected:")
        for coin, amount in crypto.items():
            print(f"      • {coin}: {amount:.8f}")
        print("")
        print("   ⚠️  NOTE: Bot can only sell positions it created")
        print("      Crypto bought outside the bot must be sold manually")
        print("")
    
    print("=" * 80)

if __name__ == "__main__":
    main()
