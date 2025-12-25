#!/usr/bin/env python3
"""
Emergency: Stop bot and check real account status
"""
import os
import subprocess
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
print("🚨 EMERGENCY: STOP BOT & CHECK REAL STATUS")
print("="*80)

# 1. Find and kill bot processes
print("\n1️⃣ CHECKING FOR RUNNING BOT PROCESSES...")
print("-" * 80)

result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
bot_processes = []

for line in result.stdout.split('\n'):
    if 'python' in line.lower() and any(x in line for x in ['main.py', 'bot.py', 'trading_strategy', 'nija']):
        parts = line.split()
        if len(parts) > 1:
            pid = parts[1]
            bot_processes.append((pid, line[:100]))

if bot_processes:
    print(f"\n🚨 FOUND {len(bot_processes)} BOT PROCESS(ES) RUNNING!")
    for pid, desc in bot_processes:
        print(f"\n   PID {pid}: {desc}...")
    
    print("\n⚠️  Bot is ACTIVELY TRADING and draining your account!")
    print("\n   Killing processes NOW...")
    
    for pid, _ in bot_processes:
        try:
            subprocess.run(['kill', '-9', pid])
            print(f"   ✅ Killed PID {pid}")
        except Exception as e:
            print(f"   ⚠️  Could not kill {pid}: {e}")
else:
    print("   ✅ No bot processes running")

# 2. Check ACTUAL account balances with full details
print("\n\n2️⃣ CHECKING REAL ACCOUNT BALANCES...")
print("-" * 80)

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

accounts = client.get_accounts()

# Handle both dict and object responses
if isinstance(accounts, dict):
    account_list = accounts.get('accounts', [])
elif hasattr(accounts, 'accounts'):
    account_list = accounts.accounts
else:
    account_list = []

print(f"\nFound {len(account_list)} total accounts")

usd_total = 0.0
crypto_holdings = []

for account in account_list:
    # Get currency
    if isinstance(account, dict):
        currency = account.get('currency', 'UNKNOWN')
        available_bal = account.get('available_balance', {})
        if isinstance(available_bal, dict):
            balance = float(available_bal.get('value', 0))
        else:
            balance = float(available_bal)
    else:
        currency = getattr(account, 'currency', 'UNKNOWN')
        if hasattr(account, 'available_balance'):
            if isinstance(account.available_balance, dict):
                balance = float(account.available_balance.get('value', 0))
            else:
                balance = float(getattr(account.available_balance, 'value', 0))
        else:
            balance = 0.0
    
    # Track non-zero balances
    if balance > 0.000001:
        if currency == 'USD':
            usd_total = balance
            print(f"\n💵 USD: ${balance:.2f}")
        else:
            crypto_holdings.append((currency, balance))
            print(f"\n🪙 {currency}: {balance:.8f}")

print("\n\n" + "="*80)
print("📊 PORTFOLIO SUMMARY")
print("="*80)

print(f"\n💵 USD Balance: ${usd_total:.2f}")

if crypto_holdings:
    print(f"\n🪙 Crypto Holdings ({len(crypto_holdings)} assets):")
    total_crypto_value = 0.0
    
    for currency, amount in crypto_holdings:
        try:
            ticker = client.get_product(f"{currency}-USD")
            if isinstance(ticker, dict):
                price = float(ticker.get('price', 0))
            else:
                price = float(getattr(ticker, 'price', 0))
            
            value = amount * price
            total_crypto_value += value
            print(f"   {currency:10} {amount:15.8f} @ ${price:.4f} = ${value:.2f}")
        except:
            print(f"   {currency:10} {amount:15.8f} (price N/A)")
    
    print(f"\n   Total Crypto Value: ${total_crypto_value:.2f}")
    print(f"\n💰 TOTAL PORTFOLIO: ${usd_total + total_crypto_value:.2f}")
else:
    print("\n   No crypto holdings")
    print(f"\n💰 TOTAL PORTFOLIO: ${usd_total:.2f}")

# 3. Recent trading activity
print("\n\n3️⃣ MOST RECENT TRADES (Last 5)...")
print("-" * 80)

orders = client.list_orders(limit=5, order_status=['FILLED'])
order_list = orders.orders if hasattr(orders, 'orders') else []

for order in order_list:
    product = getattr(order, 'product_id', 'UNKNOWN')
    side = getattr(order, 'side', 'UNKNOWN')
    created = getattr(order, 'created_time', '')[:19]
    
    if hasattr(order, 'filled_value'):
        value = float(order.filled_value)
    else:
        value = 0.0
    
    print(f"{created} | {product:12} | {side:4} | ${value:.2f}")

print("\n" + "="*80)
print("🎯 WHAT TO DO NOW")
print("="*80)

if usd_total == 0 and len(crypto_holdings) == 0:
    print("\n🚨 CRITICAL: Account is completely empty!")
    print("\n   This means ALL funds were lost to:")
    print("   • Bad trades (bought high, sold low)")
    print("   • Trading fees eating tiny positions")
    print("   • Bot trading too aggressively with insufficient capital")
    print("\n   💡 To continue:")
    print("   1. Deposit AT LEAST $50-100 (NOT $5!)")
    print("   2. Bot needs proper capital to compound")
    print("   3. $5-10 positions can't overcome 2-4% fees")
elif usd_total > 0:
    print(f"\n✅ Have ${usd_total:.2f} USD ready to trade")
    print("\n   Bot has been stopped")
    print("   Ready to resume with proper strategy")
else:
    print(f"\n⚠️  Have ${total_crypto_value:.2f} in crypto")
    print("\n   Need to liquidate to USD first")
    print("   Then can resume trading")
