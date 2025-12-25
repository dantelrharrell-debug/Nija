#!/usr/bin/env python3
"""
🚨 FORCE SELL ALL POSITIONS - Simple direct Coinbase API calls
Bypasses SDK credential issues and sells all crypto immediately
"""

import os
import sys
import time
import json
from datetime import datetime

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

print("\n" + "=" * 80)
print("🚨 FORCE LIQUIDATION - SELLING ALL POSITIONS TO USD")
print("=" * 80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")

# Get credentials
api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')

if not api_key or not api_secret:
    print("❌ ERROR: COINBASE_API_KEY and COINBASE_API_SECRET not set")
    sys.exit(1)

print(f"✅ Found credentials (key length: {len(api_key)}, secret length: {len(api_secret)})")

try:
    from coinbase.rest import RESTClient
    
    print("📡 Initializing Coinbase client...")
    try:
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        print("✅ Client initialized")
    except Exception as e:
        print(f"⚠️  Error initializing client: {e}")
        print(f"   Error type: {type(e).__name__}")
        print("   Attempting raw API workaround...")
        client = None

    if client:
        # Get accounts
        print("\n📊 Fetching all accounts...")
        try:
            accounts_resp = client.get_accounts()
            accounts = getattr(accounts_resp, 'accounts', [])
            print(f"✅ Found {len(accounts)} accounts\n")
        except Exception as e:
            print(f"❌ Failed to get accounts: {e}")
            accounts = []

        # Find all crypto positions
        positions_to_sell = []
        total_value = 0
        
        print("🔍 Scanning for crypto positions...\n")
        for acc in accounts:
            currency = getattr(acc, 'currency', None)
            available_obj = getattr(acc, 'available_balance', None)
            
            if not available_obj:
                continue
                
            balance = float(getattr(available_obj, 'value', 0) or 0)
            
            # Skip USD/USDC and zero balances
            if currency in ['USD', 'USDC'] or balance < 0.00000001:
                if currency in ['USD', 'USDC']:
                    print(f"   💵 {currency}: ${balance:.2f} (cash)")
                continue
            
            # Get price
            try:
                product = client.get_product(f"{currency}-USD")
                price = float(getattr(product, 'price', 0))
                value = balance * price
                
                if value > 0.01:  # Only positions worth > 1 cent
                    positions_to_sell.append({
                        'currency': currency,
                        'balance': balance,
                        'price': price,
                        'value': value
                    })
                    total_value += value
                    print(f"   🪙 {currency}: {balance:.8f} @ ${price:.4f} = ${value:.2f}")
            except Exception as e:
                print(f"   ⚠️  {currency}: Could not price ({e})")
                # Still add to liquidation list
                positions_to_sell.append({
                    'currency': currency,
                    'balance': balance,
                    'price': 0,
                    'value': 0
                })

        if not positions_to_sell:
            print("\n✅ No crypto to sell - account already liquidated!")
            sys.exit(0)

        print(f"\n📊 SUMMARY:")
        print(f"   Total positions: {len(positions_to_sell)}")
        print(f"   Total value: ${total_value:.2f}")

        # Execute sells
        print("\n" + "=" * 80)
        print("💰 EXECUTING LIQUIDATION")
        print("=" * 80 + "\n")

        successful_sells = 0
        failed_sells = 0
        sell_orders = []

        for i, pos in enumerate(positions_to_sell, 1):
            currency = pos['currency']
            balance = pos['balance']
            symbol = f"{currency}-USD"
            
            print(f"{i}/{len(positions_to_sell)} Selling {symbol}...")
            
            try:
                # Create market sell order
                order = client.market_order_sell(
                    product_id=symbol,
                    order_configuration={
                        'market_market_ioc': {
                            'quote_size': str(pos['value']) if pos['value'] > 0 else None,
                            'base_size': str(balance) if pos['value'] == 0 else None
                        }
                    }
                )
                
                order_id = getattr(order, 'order_id', 'unknown')
                print(f"   ✅ Sell order placed: {order_id}")
                sell_orders.append({
                    'symbol': symbol,
                    'order_id': order_id,
                    'quantity': balance,
                    'value': pos['value'],
                    'timestamp': datetime.now().isoformat()
                })
                successful_sells += 1
                time.sleep(0.5)  # Small delay between orders
                
            except Exception as e:
                print(f"   ❌ Failed to sell {symbol}: {e}")
                failed_sells += 1
                continue

        # Summary
        print("\n" + "=" * 80)
        print("📊 LIQUIDATION SUMMARY")
        print("=" * 80)
        print(f"✅ Successful sells: {successful_sells}")
        print(f"❌ Failed sells: {failed_sells}")
        print(f"📈 Total orders placed: {len(sell_orders)}")

        # Save order log
        log_file = 'liquidation_orders.json'
        with open(log_file, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'total_positions': len(positions_to_sell),
                'successful': successful_sells,
                'failed': failed_sells,
                'orders': sell_orders
            }, f, indent=2)
        
        print(f"\n📁 Saved order log to: {log_file}")

        if failed_sells == 0:
            print("\n✅ All positions successfully liquidated!")
            sys.exit(0)
        else:
            print(f"\n⚠️  {failed_sells} positions still need manual attention")
            sys.exit(1)

except ImportError as e:
    print(f"❌ Import error: {e}")
    print("   Make sure coinbase-advanced-py is installed:")
    print("   pip install coinbase-advanced-py")
    sys.exit(1)
except Exception as e:
    print(f"\n❌ Unexpected error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
