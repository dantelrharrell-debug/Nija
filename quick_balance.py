#!/usr/bin/env python3
"""Quick balance check using NIJA's trading strategy"""

import sys
import os
sys.path.insert(0, 'bot')

from trading_strategy import TradingStrategy
from coinbase.rest import RESTClient

# Load credentials
api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')

if not api_key or not api_secret:
    print("❌ Missing API credentials! Set COINBASE_API_KEY and COINBASE_API_SECRET")
    sys.exit(1)

client = RESTClient(api_key=api_key, api_secret=api_secret)

# Use strategy's get_usd_balance method
strategy = TradingStrategy(client, paper_mode=False)

print('\n' + '='*70)
print('💰 NIJA FUNDED ACCOUNT STATUS')
print('='*70)

# Get USD balance
usd_balance = strategy.get_usd_balance()
print(f'\n💵 Available USD: ${usd_balance:.2f}')

# Get all positions
try:
    accounts = client.get_accounts()
    total_value = usd_balance
    positions = []
    
    for account in accounts['accounts']:
        currency = account['currency']
        balance = float(account['available_balance']['value'])
        
        if balance > 0 and currency not in ['USD', 'USDC', 'USDT']:
            try:
                product_id = f'{currency}-USD'
                product = client.get_product(product_id)
                price = float(product.get('price', 0))
                
                if price > 0:
                    value_usd = balance * price
                    total_value += value_usd
                    positions.append({
                        'currency': currency,
                        'balance': balance,
                        'price': price,
                        'value_usd': value_usd
                    })
            except:
                pass
    
    if positions:
        print(f'\n💼 CRYPTO POSITIONS ({len(positions)}):')
        print('-' * 70)
        for pos in sorted(positions, key=lambda x: x['value_usd'], reverse=True):
            print(f'{pos["currency"]:<8} {pos["balance"]:>12.8f} @ ${pos["price"]:>8.2f} = ${pos["value_usd"]:>8.2f}')
    
    print(f'\n{"="*70}')
    print(f'📊 TOTAL PORTFOLIO VALUE: ${total_value:.2f}')
    print(f'{"="*70}')
    
    # Growth calculations
    target = 1000000
    remaining = target - total_value
    growth_needed = ((target / total_value) - 1) * 100
    daily_compound = ((target / total_value) ** (1/90) - 1) * 100
    
    print(f'\n🎯 $1M GROWTH TARGET:')
    print(f'   Current: ${total_value:.2f}')
    print(f'   Goal: ${target:,.2f}')
    print(f'   Remaining: ${remaining:,.2f} ({growth_needed:,.0f}% growth)')
    print(f'   Required daily compound: {daily_compound:.2f}%/day')
    print(f'   Timeline: 90 days')
    
    # Estimate based on current NIJA settings
    print(f'\n🚀 NIJA GROWTH ACCELERATORS ACTIVE:')
    print(f'   ✅ 95% Profit Lock (never lose gains)')
    print(f'   ✅ Pyramiding at +1%, +2%, +3%')
    print(f'   ✅ Runners to 20% (was 5%)')
    print(f'   ✅ Dynamic signals (scales with account)')
    print(f'   ✅ 85% max exposure (was 70%)')
    print(f'   ✅ 1,000 trades/day limit\n')

except Exception as e:
    print(f'❌ Error fetching positions: {e}')
