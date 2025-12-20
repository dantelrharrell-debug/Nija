#!/usr/bin/env python3
"""
FORCE CHECK AND SELL - No prompts, just check and liquidate
"""
from dotenv import load_dotenv
load_dotenv()

import os
import sys
sys.path.insert(0, '/workspaces/Nija')

from bot.broker_manager import CoinbaseBroker
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)

print("\n" + "="*80)
print("🔍 CHECKING FOR CRYPTO HOLDINGS NIJA BOUGHT")
print("="*80 + "\n")

broker = CoinbaseBroker()

if not broker.connect():
    print("❌ Connection failed")
    sys.exit(1)

print("✅ Connected to Coinbase\n")

# Get ALL accounts
print("📊 Scanning ALL accounts for crypto...")
try:
    response = broker.client.get_accounts()
    # Handle both dict and object response types
    if hasattr(response, 'accounts'):
        accounts = response.accounts
    elif isinstance(response, dict):
        accounts = response.get('accounts', [])
    else:
        accounts = []
    
    print(f"Found {len(accounts)} total accounts\n")
    
    crypto_found = []
    cash_accounts = []
    
    for account in accounts:
        # Handle both dict and object account types
        if hasattr(account, 'currency'):
            currency = account.currency
            available = float(account.available_balance.value if hasattr(account.available_balance, 'value') else 0)
            account_uuid = account.uuid if hasattr(account, 'uuid') else ''
        else:
            currency = account.get('currency', '')
            available = float(account.get('available_balance', {}).get('value', 0))
            account_uuid = account.get('uuid', '')
        
        if currency in ['USD', 'USDC']:
            if available > 0:
                cash_accounts.append({
                    'currency': currency,
                    'balance': available
                })
        elif available > 0.00000001:  # Any crypto with balance
            crypto_found.append({
                'currency': currency,
                'balance': available,
                'account_uuid': account_uuid
            })
    
    # Show cash
    print("💵 CASH ACCOUNTS:")
    if cash_accounts:
        for acc in cash_accounts:
            print(f"   {acc['currency']:6s}: ${acc['balance']:.2f}")
    else:
        print("   No cash found")
    
    total_cash = sum(acc['balance'] for acc in cash_accounts)
    print(f"   Total: ${total_cash:.2f}\n")
    
    # Show crypto
    print("🪙 CRYPTO POSITIONS:")
    if crypto_found:
        print(f"   Found {len(crypto_found)} crypto position(s):\n")
        
        total_value = 0
        for pos in crypto_found:
            # Get current price
            try:
                product_id = f"{pos['currency']}-USD"
                ticker = broker.client.get_product(product_id)
                price = float(ticker.get('price', 0))
                value = pos['balance'] * price
                total_value += value
                
                print(f"   {pos['currency']:8s} | Qty: {pos['balance']:15.8f} | Price: ${price:10.2f} | Value: ${value:10.2f}")
                pos['price'] = price
                pos['value'] = value
            except Exception as e:
                print(f"   {pos['currency']:8s} | Qty: {pos['balance']:15.8f} | (couldn't get price: {e})")
                pos['price'] = 0
                pos['value'] = 0
        
        print(f"\n   Total Crypto Value: ${total_value:.2f}")
        print(f"   COMBINED VALUE: ${total_cash + total_value:.2f}")
        
        # Auto-sell all crypto
        print("\n" + "="*80)
        print("🔥 AUTO-SELLING ALL CRYPTO IN 3 SECONDS...")
        print("="*80)
        time.sleep(3)
        
        sold_count = 0
        failed_count = 0
        total_proceeds = 0
        
        for pos in crypto_found:
            currency = pos['currency']
            quantity = pos['balance']
            product_id = f"{currency}-USD"
            
            print(f"\n📤 Selling {quantity:.8f} {currency}...", end=" ")
            
            try:
                # Place market sell order
                result = broker.place_market_order(
                    symbol=product_id,
                    side='sell',
                    quantity=quantity
                )
                
                if result and result.get('success'):
                    sold_count += 1
                    total_proceeds += pos.get('value', 0)
                    print(f"✅ SOLD (~${pos.get('value', 0):.2f})")
                else:
                    failed_count += 1
                    error_msg = result.get('error', 'Unknown error')
                    print(f"❌ FAILED: {error_msg}")
                    
            except Exception as e:
                failed_count += 1
                print(f"❌ ERROR: {str(e)}")
            
            time.sleep(0.5)  # Small delay between orders
        
        print("\n" + "="*80)
        print("📊 LIQUIDATION SUMMARY:")
        print("="*80)
        print(f"✅ Sold: {sold_count}/{len(crypto_found)} positions")
        print(f"❌ Failed: {failed_count}/{len(crypto_found)} positions")
        print(f"💰 Total proceeds: ~${total_proceeds:.2f}")
        
        if sold_count > 0:
            print("\n⏳ Waiting 5 seconds for settlement...")
            time.sleep(5)
            
            # Check new balance
            balance_info = broker.get_account_balance()
            new_balance = balance_info.get('trading_balance', 0)
            
            print(f"\n💵 UPDATED TRADING BALANCE: ${new_balance:.2f}")
            print(f"📈 Gain from sales: +${new_balance - total_cash:.2f}")
        
    else:
        print("   ✅ No crypto positions found")
        print(f"   All ${total_cash:.2f} is already in cash\n")
    
    print("\n" + "="*80)
    print("✅ SCAN COMPLETE")
    print("="*80 + "\n")

except Exception as e:
    logger.error(f"Error: {e}")
    import traceback
    traceback.print_exc()
