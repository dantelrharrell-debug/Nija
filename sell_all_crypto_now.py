#!/usr/bin/env python3
"""
Emergency Crypto Liquidation - Sell ALL crypto holdings to USD
Then shows you how to move funds to Advanced Trade
"""
import os
import sys
from coinbase.rest import RESTClient

def load_env_file():
    """Load .env file if it exists"""
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
print("💥 EMERGENCY CRYPTO LIQUIDATION")
print("="*80)

# Connect to Coinbase
try:
    client = RESTClient(
        api_key=os.getenv('COINBASE_API_KEY'),
        api_secret=os.getenv('COINBASE_API_SECRET')
    )
    print("✅ Connected to Coinbase Advanced Trade")
except Exception as e:
    print(f"❌ Connection failed: {e}")
    sys.exit(1)

# Get all accounts
print("\n📊 Scanning for crypto positions...")
accounts = client.get_accounts()
account_list = accounts.accounts if hasattr(accounts, 'accounts') else accounts.get('accounts', [])

crypto_to_sell = []
usd_balance = 0.0

for account in account_list:
    currency = account.currency
    
    if isinstance(account.available_balance, dict):
        balance = float(account.available_balance.get('value', 0))
    else:
        balance = float(account.available_balance.value)
    
    if currency == 'USD':
        usd_balance = balance
        continue
    
    if currency == 'USDC':
        # USDC doesn't need to be sold, it's already stable
        print(f"ℹ️  USDC: ${balance:.2f} (keeping as is, equivalent to USD)")
        continue
    
    # Any other crypto with balance > minimum
    if balance > 0.00000001:
        try:
            ticker = client.get_product(f"{currency}-USD")
            price = float(getattr(ticker, 'price', 0))
            value = balance * price
            
            # Only sell if value > $0.10 (avoid dust)
            if value > 0.10:
                crypto_to_sell.append({
                    'currency': currency,
                    'balance': balance,
                    'price': price,
                    'value': value
                })
                print(f"🔍 Found: {balance:.8f} {currency} (${value:.2f})")
        except Exception as e:
            print(f"⚠️  {currency}: {balance:.8f} (could not get price: {e})")

if not crypto_to_sell:
    print("\n✅ No crypto positions to sell!")
    print(f"💵 Current USD balance: ${usd_balance:.2f}")
    print("\n" + "="*80)
    sys.exit(0)

# Show what will be sold
print("\n" + "-"*80)
print("POSITIONS TO LIQUIDATE:")
print("-"*80)
total_value = sum(p['value'] for p in crypto_to_sell)
for pos in crypto_to_sell:
    print(f"  • {pos['currency']}: {pos['balance']:.8f} @ ${pos['price']:.2f} = ${pos['value']:.2f}")
print(f"\n💰 Total estimated proceeds: ${total_value:.2f}")
print(f"💵 Current USD balance: ${usd_balance:.2f}")
print(f"🎯 Expected after sale: ${usd_balance + total_value:.2f}")

# Confirm
print("\n" + "="*80)
print("⚠️  WARNING: This will sell ALL crypto positions!")
print("="*80)
confirm = input("\nType 'SELL NOW' to proceed: ")

if confirm.strip() != "SELL NOW":
    print("\n❌ Cancelled - no positions sold")
    sys.exit(0)

# Execute sales
print("\n" + "="*80)
print("🔥 SELLING POSITIONS...")
print("="*80)

sold_count = 0
failed_count = 0
total_sold_value = 0.0

for pos in crypto_to_sell:
    currency = pos['currency']
    balance = pos['balance']
    
    try:
        print(f"\n🔄 Selling {currency}...")
        
        # Place market sell order
        order = client.market_order_sell(
            product_id=f"{currency}-USD",
            base_size=str(balance)
        )
        
        # Check if order succeeded
        if hasattr(order, 'success') and order.success:
            print(f"✅ {currency} sold successfully")
            sold_count += 1
            total_sold_value += pos['value']
        else:
            error_msg = getattr(order, 'error_response', {}).get('message', 'Unknown error')
            print(f"❌ {currency} sale failed: {error_msg}")
            failed_count += 1
            
    except Exception as e:
        print(f"❌ {currency} sale failed: {e}")
        failed_count += 1

# Summary
print("\n" + "="*80)
print("LIQUIDATION COMPLETE")
print("="*80)
print(f"\n✅ Sold: {sold_count} positions (~${total_sold_value:.2f})")
print(f"❌ Failed: {failed_count} positions")

if sold_count > 0:
    print("\n⏳ Waiting for sales to settle...")
    import time
    time.sleep(3)
    
    # Get new balance
    print("\n📊 Checking updated balance...")
    accounts = client.get_accounts()
    account_list = accounts.accounts if hasattr(accounts, 'accounts') else accounts.get('accounts', [])
    
    new_usd = 0.0
    new_usdc = 0.0
    for account in account_list:
        if account.currency == 'USD':
            if isinstance(account.available_balance, dict):
                new_usd = float(account.available_balance.get('value', 0))
            else:
                new_usd = float(account.available_balance.value)
        elif account.currency == 'USDC':
            if isinstance(account.available_balance, dict):
                new_usdc = float(account.available_balance.get('value', 0))
            else:
                new_usdc = float(account.available_balance.value)
    
    print(f"\n💵 USD: ${new_usd:.2f}")
    print(f"💵 USDC: ${new_usdc:.2f}")
    print(f"💰 Total: ${new_usd + new_usdc:.2f}")
    
    # Check if this is in Advanced Trade or Consumer
    print("\n" + "="*80)
    print("🔍 CHECKING WHERE YOUR FUNDS ARE...")
    print("="*80)
    
    # Check if funds are tradable
    if new_usd + new_usdc < 10.00:
        print("\n⚠️  Still low balance - check if funds went to Consumer wallet")
        print("\n📝 HOW TO MOVE FUNDS TO ADVANCED TRADE:")
        print("   1. Go to: https://www.coinbase.com/advanced-trade")
        print("   2. Click 'Deposit' button (top right)")
        print("   3. Choose 'From Coinbase' (your Consumer wallet)")
        print("   4. Transfer your USD/USDC to Advanced Trade")
        print("   5. Wait 2-3 minutes for transfer to complete")
    else:
        print("\n✅ You now have trading balance!")
        print("\nℹ️  If bot still can't trade, transfer to Advanced Trade:")
        print("   https://www.coinbase.com/advanced-trade → Deposit → From Coinbase")

print("\n" + "="*80 + "\n")
