#!/usr/bin/env python3
"""
FORCE SELL ALL CRYPTO FROM ALL PORTFOLIOS
Sells crypto from Consumer wallet AND Advanced Trade
"""

import sys
import os
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from coinbase.rest import RESTClient
from dotenv import load_dotenv

load_dotenv()

print("=" * 80)
print("🚨 EMERGENCY LIQUIDATION - ALL PORTFOLIOS")
print("=" * 80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Get ALL accounts
print("🔍 Scanning ALL portfolios for crypto...")
accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

consumer_crypto = []
advanced_crypto = []

for acc in accounts:
    curr = getattr(acc, 'currency', None)
    avail_obj = getattr(acc, 'available_balance', None)
    acc_type = getattr(acc, 'type', 'UNKNOWN')
    
    if not curr or not avail_obj:
        continue
    
    if curr in ['USD', 'USDC']:
        continue  # Skip cash
    
    amount = float(getattr(avail_obj, 'value', 0))
    
    if amount <= 0:
        continue
    
    crypto_info = {
        'currency': curr,
        'amount': amount,
        'symbol': f"{curr}-USD",
        'type': acc_type
    }
    
    if acc_type == 'ACCOUNT':
        consumer_crypto.append(crypto_info)
    else:
        advanced_crypto.append(crypto_info)

total_positions = len(consumer_crypto) + len(advanced_crypto)

if total_positions == 0:
    print("\n✅ No crypto positions found in ANY portfolio")
    print("=" * 80)
    sys.exit(0)

print(f"\n📊 CRYPTO POSITIONS FOUND:\n")

if consumer_crypto:
    print("📦 Consumer Wallet:")
    for c in consumer_crypto:
        print(f"  • {c['currency']}: {c['amount']:.8f}")
    print()

if advanced_crypto:
    print("📦 Advanced Trade:")
    for c in advanced_crypto:
        print(f"  • {c['currency']}: {c['amount']:.8f}")
    print()

print(f"Total positions to liquidate: {total_positions}")

print("\n" + "=" * 80)
print("⚠️  STARTING LIQUIDATION...")
print("=" * 80 + "\n")

sold = 0
failed = 0
errors = []

# Sell everything
all_crypto = consumer_crypto + advanced_crypto

for crypto in all_crypto:
    symbol = crypto['symbol']
    currency = crypto['currency']
    amount = crypto['amount']
    location = "Consumer" if crypto['type'] == 'ACCOUNT' else "Advanced"
    
    try:
        print(f"📤 [{location}] Selling {amount:.8f} {currency}...")
        
        # Place market sell order
        # Note: Consumer wallet crypto should still be sellable via API
        order = client.market_order_sell(
            product_id=symbol,
            base_size=str(amount)
        )
        
        if order and hasattr(order, 'success') and getattr(order, 'success', False):
            print(f"  ✅ SOLD {currency}")
            sold += 1
        else:
            error_msg = getattr(order, 'error_response', 'Unknown error') if order else 'No response'
            if hasattr(order, 'failure_reason'):
                error_msg = getattr(order, 'failure_reason', error_msg)
            
            print(f"  ❌ FAILED: {error_msg}")
            failed += 1
            errors.append(f"{currency}: {error_msg}")
            
    except Exception as e:
        print(f"  ❌ ERROR: {e}")
        failed += 1
        errors.append(f"{currency}: {str(e)}")

print("\n" + "=" * 80)
print("📊 LIQUIDATION RESULTS")
print("=" * 80)
print(f"✅ Successfully sold: {sold}/{total_positions}")
print(f"❌ Failed to sell: {failed}/{total_positions}")

if errors:
    print("\n❌ ERRORS ENCOUNTERED:")
    for error in errors:
        print(f"  • {error}")
    
    print("\n💡 TROUBLESHOOTING:")
    print("   If sales failed, crypto may be:")
    print("   1. Locked in staking/rewards")
    print("   2. Below minimum trade size")
    print("   3. In unsupported trading pairs")
    print("\n   MANUAL ACTION REQUIRED:")
    print("   Go to https://www.coinbase.com")
    print("   Sell manually through the web interface")

print("\n" + "=" * 80)

if sold > 0:
    print("\n💰 Cash should now be available!")
    print("   Check balance: python3 CHECK_CASH_LOCATION.py")
    print("\n   If cash is in Consumer wallet:")
    print("   Transfer to Advanced Trade so bot can trade")

print("=" * 80)
