#!/usr/bin/env python3
"""
Sell APT position and resume 15-day goal trading
"""
import os
import uuid
from coinbase.rest import RESTClient

# Load .env
def load_env_file():
    if not os.path.exists('.env'):
        return False
    with open('.env', 'r') as f:
        content = f.read()
    current_key = None
    current_value = []
    for line in content.split('\n'):
        if line.startswith('#') or not line.strip():
            continue
        if '=' in line and not line.startswith(' '):
            if current_key:
                os.environ[current_key] = '\n'.join(current_value)
            key, value = line.split('=', 1)
            current_key = key.strip()
            current_value = [value.strip()]
        else:
            if current_key:
                current_value.append(line)
    if current_key:
        os.environ[current_key] = '\n'.join(current_value)
    return True

load_env_file()

print("\n" + "="*80)
print("🚀 15-DAY GOAL: LIQUIDATE APT & RESUME TRADING")
print("="*80)
print("\n📊 Current Status:")
print("   APT Holdings: 6.546 APT (~$9.99)")
print("   USD Balance: $0.00")
print("   Goal: $5,000 in 13 days remaining")
print("   Strategy: ULTRA AGGRESSIVE (8-40% positions)")

print("\n⚡ Action Plan:")
print("   1. Sell 6.546 APT → Get ~$9.99 USD")
print("   2. Resume bot with ULTRA AGGRESSIVE settings")
print("   3. Bot will trade aggressively to compound up")

confirm = input("\nSell APT and resume trading? (yes/no): ")

if confirm.lower() != 'yes':
    print("\n❌ Cancelled")
    exit(0)

try:
    client = RESTClient(
        api_key=os.getenv('COINBASE_API_KEY'),
        api_secret=os.getenv('COINBASE_API_SECRET')
    )
    
    print("\n🔄 Selling APT...")
    print("-" * 80)
    
    # Sell APT
    order = client.market_order_sell(
        client_order_id=str(uuid.uuid4()),
        product_id="APT-USD",
        base_size="6.546"
    )
    
    print("✅ APT SOLD!")
    print(f"   Order ID: {getattr(order, 'order_id', 'N/A')[:20]}...")
    
    import time
    time.sleep(2)
    
    # Check new balance
    accounts = client.get_accounts()
    account_list = accounts.accounts if hasattr(accounts, 'accounts') else []
    
    usd_balance = 0.0
    for account in account_list:
        if account.currency == 'USD':
            usd_balance = float(account.available_balance.value)
            break
    
    print(f"\n💰 New USD Balance: ${usd_balance:.2f}")
    
    print("\n" + "="*80)
    print("🎯 READY TO RESUME 15-DAY GOAL TRADING")
    print("="*80)
    
    print(f"\nStarting Balance: ${usd_balance:.2f}")
    print(f"Target: $5,000")
    print(f"Days Remaining: 13")
    print(f"Required Daily Return: ~40% (adjusted for time lost)")
    
    print("\n✅ Bot Configuration:")
    print("   • Position Size: 8-40% (adaptive)")
    print("   • Concurrent Positions: 8")
    print("   • Markets: 50 top cryptos")
    print("   • Scan Frequency: 15 seconds")
    print("   • Risk Level: ULTRA AGGRESSIVE")
    
    print("\n🚀 NEXT STEPS:")
    print("   1. Bot is ready with ULTRA AGGRESSIVE settings")
    print("   2. Will automatically trade and compound")
    print("   3. Monitor progress in logs")
    print("   4. Balance will auto-adjust risk at $300, $1K, $3K")
    
    print("\n💡 To start bot:")
    print("   python3 main.py")
    print("   OR")
    print("   Deploy to Railway/Render for 24/7 trading")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
