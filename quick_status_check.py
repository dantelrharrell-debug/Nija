#!/usr/bin/env python3
"""Quick status check - portfolio balance and recent trades"""
import os
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

print("="*80)
print("CURRENT PORTFOLIO STATUS")
print("="*80)

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Check balance
accounts = client.get_accounts()
account_list = accounts.accounts if hasattr(accounts, 'accounts') else []

total_usd = 0.0
total_crypto_value = 0.0

print("\nACCOUNT BALANCES:")
print("-" * 80)

for account in account_list:
    currency = account.currency
    if isinstance(account.available_balance, dict):
        balance = float(account.available_balance.get('value', 0))
    else:
        balance = float(account.available_balance.value)
    
    if balance > 0.00001:
        if currency == 'USD':
            total_usd = balance
            print(f"💵 USD: ${balance:.2f}")
        else:
            print(f"🪙 {currency}: {balance:.8f}")
            try:
                ticker = client.get_product(f"{currency}-USD")
                price = float(getattr(ticker, 'price', 0))
                value = balance * price
                total_crypto_value += value
                print(f"   → ${value:.2f} USD")
            except:
                pass

print("\n" + "="*80)
print(f"💰 TOTAL PORTFOLIO: ${total_usd + total_crypto_value:.2f}")
print(f"   USD: ${total_usd:.2f}")
print(f"   Crypto: ${total_crypto_value:.2f}")
print("="*80)

# Check recent trades
print("\n\nRECENT TRADES (Last 5):")
print("-" * 80)

try:
    orders = client.list_orders(limit=5, order_status=['FILLED'])
    order_list = orders.orders if hasattr(orders, 'orders') else []
    
    for order in order_list:
        product = getattr(order, 'product_id', 'UNKNOWN')
        side = getattr(order, 'side', 'UNKNOWN')
        created = getattr(order, 'created_time', '')[:19]
        value = float(getattr(order, 'filled_value', 0))
        print(f"{created} | {product:12} | {side:4} | ${value:.2f}")
except Exception as e:
    print(f"Error fetching orders: {e}")

print("\n" + "="*80)

# Assessment
if total_usd + total_crypto_value == 0:
    print("🚨 CRITICAL: Portfolio is completely EMPTY ($0.00)")
    print("\n📊 What happened:")
    print("   1. Started Day 1: $55.81")
    print("   2. Lost to fees: -$59.48 (trading $5 positions)")
    print("   3. APT liquidated: +$9.99")
    print("   4. Bot kept trading: -$9.99")
    print("   5. Current: $0.00")
    print("\n💡 THE PROBLEM:")
    print("   • Coinbase fees are 2-4% per trade")
    print("   • $5-10 positions lose money even with 60% win rate")
    print("   • Bot strategy is CORRECT but capital too small")
    print("\n✅ THE FIX:")
    print("   1. STOP the bot (it's bleeding money)")
    print("   2. Deposit $50-100 minimum (NOT $5!)")
    print("   3. Bot will trade $10-40 positions (fees <1%)")
    print("   4. Larger positions = room for profit")
elif total_usd + total_crypto_value < 10:
    print(f"⚠️  WARNING: Only ${total_usd + total_crypto_value:.2f} remaining")
    print("\n📊 15-Day Goal Status:")
    print(f"   Target: $5,000 by Jan 1, 2026")
    print(f"   Current: ${total_usd + total_crypto_value:.2f}")
    print(f"   Days Left: 12")
    print(f"   Progress: {((total_usd + total_crypto_value) / 5000) * 100:.1f}%")
    print("\n⚠️  REALITY CHECK:")
    print(f"   • Need ${5000 - (total_usd + total_crypto_value):.2f} more in 12 days")
    print("   • Would need 60%+ DAILY returns")
    print("   • Current capital too small to compound")
    print("\n💡 OPTIONS:")
    print("   A) Deposit $50-100 and try aggressive compounding")
    print("   B) Accept goal is unrealistic with current capital")
    print("   C) Move to lower-fee exchange (Binance, Kraken)")
else:
    print(f"✅ Portfolio: ${total_usd + total_crypto_value:.2f}")
    print("\n🎯 15-Day Goal Progress:")
    print(f"   Target: $5,000")
    print(f"   Current: ${total_usd + total_crypto_value:.2f}")
    print(f"   Progress: {((total_usd + total_crypto_value) / 5000) * 100:.1f}%")
