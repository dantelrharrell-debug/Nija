#!/usr/bin/env python3
"""Quick balance checker for NIJA trading account"""

import sys
sys.path.insert(0, 'bot')

from coinbase.rest import RESTClient
import os

def main():
    client = RESTClient(
        api_key=os.getenv('COINBASE_API_KEY'), 
        api_secret=os.getenv('COINBASE_API_SECRET')
    )
    
    print('\n' + '='*70)
    print('💰 CURRENT FUNDED ACCOUNT STATUS')
    print('='*70)
    
    accounts = client.get_accounts()
    total_usd = 0
    positions = []
    
    for account in accounts['accounts']:
        currency = account['currency']
        balance = float(account['available_balance']['value'])
        
        if balance > 0:
            if currency in ['USD', 'USDC', 'USDT']:
                total_usd += balance
                if balance > 0.01:
                    print(f'\n💵 {currency}: ${balance:.2f}')
            else:
                try:
                    product_id = f'{currency}-USD'
                    product = client.get_product(product_id)
                    price = float(product.get('price', 0))
                    
                    if price > 0:
                        value_usd = balance * price
                        total_usd += value_usd
                        positions.append({
                            'currency': currency,
                            'balance': balance,
                            'price': price,
                            'value_usd': value_usd
                        })
                except:
                    pass
    
    print(f'\n{"="*70}')
    print(f'📊 TOTAL PORTFOLIO VALUE: ${total_usd:.2f}')
    print(f'{"="*70}')
    
    if positions:
        print(f'\n💼 CRYPTO POSITIONS ({len(positions)}):')
        print('-' * 70)
        for pos in sorted(positions, key=lambda x: x['value_usd'], reverse=True):
            print(f'{pos["currency"]:<8} {pos["balance"]:>12.8f} @ ${pos["price"]:>8.2f} = ${pos["value_usd"]:>8.2f}')
    
    print(f'\n📈 GROWTH TARGET: ${total_usd:.2f} → $1,000,000 (90 days)')
    print(f'🎯 Remaining: ${1000000 - total_usd:,.2f} ({((1000000/total_usd)-1)*100:,.0f}% growth needed)')
    print(f'📊 Daily Compound Required: {((1000000/total_usd)**(1/90)-1)*100:.2f}%/day\n')

if __name__ == '__main__':
    main()
