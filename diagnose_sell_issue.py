#!/usr/bin/env python3
"""
Diagnose why bot is buying but not selling
Checks:
1. Open positions in bot's memory
2. Actual crypto holdings in Coinbase
3. Bot sell order logic
4. Recent error logs
"""
import os
import sys

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseBroker
from coinbase.rest import RESTClient

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
print("🔍 DIAGNOSING BOT SELL ORDER ISSUE")
print("="*80)

# Check Coinbase holdings
print("\n📊 STEP 1: Checking actual Coinbase holdings...")
print("-"*80)

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

accounts = client.get_accounts()
account_list = accounts.accounts if hasattr(accounts, 'accounts') else accounts.get('accounts', [])

crypto_count = 0
total_value = 0

for account in account_list:
    currency = account.currency
    
    if isinstance(account.available_balance, dict):
        balance = float(account.available_balance.get('value', 0))
    else:
        balance = float(account.available_balance.value)
    
    if currency != 'USD' and balance > 0.00000001:
        crypto_count += 1
        try:
            ticker = client.get_product(f"{currency}-USD")
            price = float(getattr(ticker, 'price', 0))
            value = balance * price
            total_value += value
            print(f"   🪙 {currency}: {balance:.8f} @ ${price:.2f} = ${value:.2f}")
        except:
            print(f"   🪙 {currency}: {balance:.8f} (could not get price)")

print(f"\n   Total: {crypto_count} positions worth ${total_value:.2f}")

# Check bot logic
print("\n\n📝 STEP 2: Analyzing bot sell order logic...")
print("-"*80)

broker = CoinbaseBroker()
if broker.connect():
    print("   ✅ Broker connected successfully")
    balance = broker.get_account_balance()
    print(f"   💰 Trading balance: ${balance.get('trading_balance', 0):.2f}")
else:
    print("   ❌ Broker connection failed")

# Check for position files
print("\n\n📁 STEP 3: Checking for saved position files...")
print("-"*80)

position_files = [
    'bot/positions.json',
    'positions.json',
    'bot/open_positions.json',
    'open_positions.json'
]

found_any = False
for pfile in position_files:
    if os.path.exists(pfile):
        print(f"   ✅ Found: {pfile}")
        found_any = True
        with open(pfile, 'r') as f:
            content = f.read()
            print(f"      Content preview: {content[:200]}...")
    
if not found_any:
    print("   ℹ️  No position files found")

# Diagnosis summary
print("\n\n" + "="*80)
print("🔬 DIAGNOSIS SUMMARY")
print("="*80)

if crypto_count == 0:
    print("\n✅ NO ISSUE: No crypto positions in account")
elif crypto_count > 0:
    print(f"\n⚠️  ISSUE CONFIRMED: {crypto_count} crypto positions found (${total_value:.2f})")
    print("\nPossible causes:")
    print("   1. Bot is placing buy orders successfully")
    print("   2. Bot's sell order logic is failing or not triggering")
    print("   3. Stop-loss/take-profit conditions not being met")
    print("   4. Sell orders being rejected by Coinbase API")
    
    print("\n🔧 Recommended fixes:")
    print("   1. Check logs for sell order errors:")
    print("      grep -i 'sell\\|exit\\|close' bot_logs.txt")
    print("\n   2. Manually liquidate positions:")
    print("      python3 emergency_liquidate.py")
    print("\n   3. Review trading_strategy.py line 810-870")
    print("      Check place_market_order() calls for sells")
    print("\n   4. Verify stop-loss/take-profit triggers:")
    print("      Check if exit_reason is being set correctly")

print("\n" + "="*80 + "\n")
