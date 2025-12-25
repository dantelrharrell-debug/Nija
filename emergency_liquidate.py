#!/usr/bin/env python3
"""
EMERGENCY LIQUIDATION - Sell ALL crypto immediately (no confirmation needed)
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
print("🚨 EMERGENCY LIQUIDATION - SELLING ALL CRYPTO NOW")
print("="*80)

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Get all accounts
print("\n🔍 Finding crypto positions...")
try:
    accounts = client.get_accounts()
    account_list = accounts.accounts if hasattr(accounts, 'accounts') else accounts.get('accounts', [])
except Exception as e:
    print(f"❌ Failed to fetch accounts from Coinbase: {e}")
    print("\nTroubleshooting:")
    print("  • Verify .env contains COINBASE_API_KEY and COINBASE_API_SECRET")
    print("  • Confirm keys have Advanced Trade permissions (read + trade)")
    print("  • Run: python3 test_raw_api.py or python3 test_api_connection.py")
    print("  • If using PEM-based JWT, ensure COINBASE_PEM_CONTENT or file is set")
    exit(1)

positions_to_sell = []

for account in account_list:
    currency = account.currency
    
    if isinstance(account.available_balance, dict):
        balance = float(account.available_balance.get('value', 0))
    else:
        balance = float(account.available_balance.value)
    
    # Skip USD and zero balances
    if currency == 'USD' or balance < 0.00000001:
        continue
    
    # Get price and value
    try:
        ticker = client.get_product(f"{currency}-USD")
        price = float(getattr(ticker, 'price', 0))
        value = balance * price
        
        if value > 0.01:  # Only positions worth > 1 cent
            positions_to_sell.append({
                'currency': currency,
                'balance': balance,
                'price': price,
                'value': value
            })
    except Exception as e:
        print(f"⚠️  Could not price {currency}: {e}")
        # Still try to sell it
        positions_to_sell.append({
            'currency': currency,
            'balance': balance,
            'price': 0,
            'value': 0
        })

if not positions_to_sell:
    print("\n✅ No crypto to sell - account already in USD")
    
    # Show USD balance
    for account in account_list:
        if account.currency == 'USD':
            if isinstance(account.available_balance, dict):
                usd = float(account.available_balance.get('value', 0))
            else:
                usd = float(account.available_balance.value)
            print(f"💵 USD Balance: ${usd:.2f}")
    print()
    exit(0)

print(f"\n📊 Found {len(positions_to_sell)} positions to sell")
print("-"*80)

total_value = sum(p['value'] for p in positions_to_sell)
print(f"Total crypto value: ${total_value:.2f}\n")

for pos in positions_to_sell:
    print(f"{pos['currency']:8} {pos['balance']:15.8f} @ ${pos['price']:10.2f} = ${pos['value']:.2f}")

print("\n🔥 LIQUIDATING ALL POSITIONS...")
print("="*80)

successful = 0
failed = 0
total_recovered = 0.0
failed_positions = []

for pos in positions_to_sell:
    currency = pos['currency']
    balance = pos['balance']
    value = pos['value']
    
    print(f"\n💸 Selling {currency}...")
    print(f"   Amount: {balance:.8f}")
    print(f"   Est. Value: ${value:.2f}")
    
    try:
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
            error_msg = order.get('error_response', {}).get('message', 'Unknown error')
        else:
            success = getattr(order, 'success', False)
            order_id = getattr(order, 'order_id', 'UNKNOWN')
            error_msg = getattr(getattr(order, 'error_response', {}), 'message', 'Unknown error')
        
        if success:
            time.sleep(1.5)  # Wait for fill
            
            try:
                order_details = client.get_order(order_id)
                if isinstance(order_details, dict):
                    filled_value = float(order_details.get('filled_value', value))
                else:
                    filled_value = float(getattr(order_details, 'filled_value', value))
                
                total_recovered += filled_value
                print(f"   ✅ SOLD for ${filled_value:.2f}")
                successful += 1
            except:
                print(f"   ✅ SOLD (estimated: ~${value:.2f})")
                total_recovered += value
                successful += 1
        else:
            print(f"   ❌ FAILED: {error_msg}")
            failed += 1
            failed_positions.append((currency, error_msg))
        
        time.sleep(0.5)  # Rate limiting
        
    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        failed += 1
        failed_positions.append((currency, str(e)))

# Final summary
print("\n\n" + "="*80)
print("📊 LIQUIDATION RESULTS")
print("="*80)

print(f"\n✅ Successful: {successful}/{len(positions_to_sell)}")
print(f"❌ Failed:     {failed}/{len(positions_to_sell)}")
print(f"\n💰 USD Recovered: ${total_recovered:.2f}")

if failed_positions:
    print("\n⚠️  FAILED POSITIONS:")
    for currency, error in failed_positions:
        print(f"   {currency}: {error}")

# Check final balance
time.sleep(2)
print("\n🔍 Checking final balance...")

accounts = client.get_accounts()
account_list = accounts.accounts if hasattr(accounts, 'accounts') else accounts.get('accounts', [])

usd_balance = 0.0
remaining_crypto = 0.0
remaining_positions = []

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
            value = balance * price
            remaining_crypto += value
            remaining_positions.append((currency, balance, value))
        except:
            pass

print("\n" + "="*80)
print("💰 FINAL PORTFOLIO")
print("="*80)

print(f"\n💵 USD:   ${usd_balance:.2f}")

if remaining_crypto > 0:
    print(f"🪙 Crypto: ${remaining_crypto:.2f}")
    print("\n⚠️  Remaining positions:")
    for currency, balance, value in remaining_positions:
        print(f"   {currency}: {balance:.8f} (${value:.2f})")

print(f"\n💰 TOTAL: ${usd_balance + remaining_crypto:.2f}")

print("\n" + "="*80)

if remaining_crypto > 0:
    print("\n⚠️  Some crypto remains - may need manual intervention")
    print("   Check Coinbase web interface to sell manually")
else:
    print("\n✅ ALL CRYPTO LIQUIDATED - FULLY IN USD")

print("\n" + "="*80 + "\n")
