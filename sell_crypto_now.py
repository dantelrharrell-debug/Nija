#!/usr/bin/env python3
"""
Sell ALL crypto positions immediately to recover USD
"""
import os
import uuid
import time
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
print("💰 LIQUIDATING ALL CRYPTO POSITIONS")
print("="*80)

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Get all accounts
print("\n🔍 Finding crypto holdings...")
accounts = client.get_accounts()
account_list = accounts.accounts if hasattr(accounts, 'accounts') else []

positions = []
total_crypto_value = 0.0

for account in account_list:
    currency = account.currency
    if isinstance(account.available_balance, dict):
        balance = float(account.available_balance.get('value', 0))
    else:
        balance = float(account.available_balance.value)
    
    # Skip USD and zero balances
    if currency == 'USD' or balance < 0.00000001:
        continue
    
    # Get USD value
    try:
        ticker = client.get_product(f"{currency}-USD")
        price = float(getattr(ticker, 'price', 0))
        value_usd = balance * price
        
        if value_usd > 0.01:  # Only positions worth > 1 cent
            positions.append({
                'currency': currency,
                'balance': balance,
                'price': price,
                'value': value_usd
            })
            total_crypto_value += value_usd
    except Exception as e:
        print(f"⚠️  Could not price {currency}: {e}")

if not positions:
    print("\n✅ No crypto to sell - account is already in USD")
    
    # Check USD balance
    for account in account_list:
        if account.currency == 'USD':
            if isinstance(account.available_balance, dict):
                usd = float(account.available_balance.get('value', 0))
            else:
                usd = float(account.available_balance.value)
            print(f"\n💵 USD Balance: ${usd:.2f}")
            
            if usd == 0:
                print("\n🚨 WARNING: Portfolio is completely empty ($0.00)")
                print("\n📊 What this means:")
                print("   • All funds depleted from trading losses")
                print("   • Bot burned through capital via fees")
                print("   • Need to deposit fresh funds to continue")
                print("\n💡 Next steps:")
                print("   1. Deposit $100-200 to Coinbase Advanced Trade")
                print("   2. Bot will automatically start when balance > $50")
                print("   3. Larger positions = lower fee % = profitable")
            elif usd < 50:
                print(f"\n⚠️  WARNING: Balance (${usd:.2f}) too low for profitable trading")
                print("\n📊 Why this won't work:")
                print(f"   • Position sizes would be: ${usd * 0.08:.2f} - ${usd * 0.40:.2f}")
                print("   • Fees: 2-4% per trade")
                print("   • Even winning trades lose money")
                print("\n💡 Recommendation:")
                print(f"   • Add ${50 - usd:.2f} to reach $50 minimum")
                print("   • OR deposit to reach $100+ for best results")
            else:
                print(f"\n✅ Ready to trade with ${usd:.2f}!")
    exit(0)

print(f"\n📊 Found {len(positions)} crypto position(s) worth ${total_crypto_value:.2f}:")
print("-" * 80)

for pos in positions:
    print(f"{pos['currency']:8} {pos['balance']:15.8f} @ ${pos['price']:10.2f} = ${pos['value']:.2f}")

print("\n🔄 SELLING ALL POSITIONS...")
print("="*80)

successful = 0
failed = 0
total_recovered = 0.0

for pos in positions:
    currency = pos['currency']
    balance = pos['balance']
    value = pos['value']
    
    try:
        print(f"\n💸 Selling {currency}...")
        print(f"   Amount: {balance:.8f}")
        print(f"   Est. Value: ${value:.2f}")
        
        # Place market sell order
        order = client.market_order_sell(
            client_order_id=str(uuid.uuid4()),
            product_id=f"{currency}-USD",
            base_size=str(balance)
        )
        
        # Check success
        if isinstance(order, dict):
            success = order.get('success', False)
            order_id = order.get('order_id', 'UNKNOWN')
        else:
            success = getattr(order, 'success', False)
            order_id = getattr(order, 'order_id', 'UNKNOWN')
        
        if success:
            time.sleep(1)  # Wait for fill
            
            try:
                order_details = client.get_order(order_id)
                if isinstance(order_details, dict):
                    filled_value = float(order_details.get('filled_value', 0))
                else:
                    filled_value = float(getattr(order_details, 'filled_value', 0))
                
                total_recovered += filled_value
                print(f"   ✅ SOLD for ${filled_value:.2f}")
                successful += 1
            except:
                print(f"   ✅ SOLD (value: ~${value:.2f})")
                total_recovered += value
                successful += 1
        else:
            print(f"   ❌ FAILED")
            failed += 1
        
        time.sleep(0.5)  # Rate limit
        
    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        failed += 1

# Final summary
print("\n\n" + "="*80)
print("✅ LIQUIDATION COMPLETE")
print("="*80)

print(f"\nResults:")
print(f"   ✅ Sold: {successful}/{len(positions)}")
print(f"   ❌ Failed: {failed}/{len(positions)}")
print(f"\n💰 Recovered: ${total_recovered:.2f}")

# Check final balance
time.sleep(2)
print("\n🔍 Checking final balance...")

accounts = client.get_accounts()
account_list = accounts.accounts if hasattr(accounts, 'accounts') else []

usd_balance = 0.0
remaining_crypto = 0.0

for account in account_list:
    currency = account.currency
    if isinstance(account.available_balance, dict):
        balance = float(account.available_balance.get('value', 0))
    else:
        balance = float(account.available_balance.value)
    
    if currency == 'USD':
        usd_balance = balance
    elif balance > 0.00000001:
        try:
            ticker = client.get_product(f"{currency}-USD")
            price = float(getattr(ticker, 'price', 0))
            remaining_crypto += balance * price
        except:
            pass

print("\n" + "="*80)
print("📊 FINAL PORTFOLIO STATUS")
print("="*80)

print(f"\n💵 USD: ${usd_balance:.2f}")
if remaining_crypto > 0:
    print(f"🪙 Remaining Crypto: ${remaining_crypto:.2f}")
print(f"💰 Total: ${usd_balance + remaining_crypto:.2f}")

print("\n" + "="*80)

if usd_balance + remaining_crypto == 0:
    print("🚨 PORTFOLIO EMPTY - TRADING NOT POSSIBLE")
    print("\n💡 To continue:")
    print("   1. Deposit $100-200 to Coinbase Advanced Trade")
    print("   2. Bot requires $50 minimum to start")
    print("   3. Recommended: $100+ for profitable trading")
elif usd_balance + remaining_crypto < 50:
    print(f"⚠️  BALANCE TOO LOW FOR PROFITABLE TRADING")
    print(f"\n   Current: ${usd_balance + remaining_crypto:.2f}")
    print(f"   Needed: $50 minimum (bot won't start)")
    print(f"   Recommended: $100+ for best results")
    print(f"\n   Deposit: ${50 - (usd_balance + remaining_crypto):.2f} to reach minimum")
else:
    print(f"✅ READY TO TRADE")
    print(f"\n   Balance: ${usd_balance:.2f}")
    print(f"   Bot will start automatically (balance > $50)")
    print(f"   Position sizes: ${usd_balance * 0.08:.2f} - ${usd_balance * 0.40:.2f}")

print("\n" + "="*80)
