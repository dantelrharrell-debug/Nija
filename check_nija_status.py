#!/usr/bin/env python3
"""Check NIJA current balance, profit, and trading account location"""

import sys
import os
sys.path.insert(0, 'bot')

from coinbase.rest import RESTClient

def main():
    print('\n' + '='*80)
    print('🤖 NIJA TRADING BOT - CURRENT STATUS')
    print('='*80)
    print()
    
    # Check for credentials
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    
    print('🔐 Credential Check:')
    print(f'   API Key: {"✅ Set" if api_key else "❌ Missing"}')
    print(f'   API Secret: {"✅ Set" if api_secret else "❌ Missing"}')
    print()
    
    if not api_key or not api_secret:
        print('❌ ERROR: Coinbase API credentials not found!')
        print('   Set environment variables:')
        print('   - COINBASE_API_KEY')
        print('   - COINBASE_API_SECRET')
        print()
        print('💡 These should be set in your .env file or deployment environment')
        return
    
    try:
        # Initialize Coinbase client
        print('🔌 Connecting to Coinbase Advanced Trade API...')
        client = RESTClient(
            api_key=api_key,
            api_secret=api_secret
        )
        
        # Get all accounts
        accounts_response = client.get_accounts()
        accounts = accounts_response.get('accounts', [])
        
        print(f'✅ Connected - Found {len(accounts)} accounts')
        print()
        
        # Parse accounts
        usd_balance = 0
        usdc_balance = 0
        positions = []
        total_cash = 0
        
        print('='*80)
        print('💰 ACCOUNT BREAKDOWN:')
        print('='*80)
        print()
        
        for account in accounts:
            currency = account.get('currency', '')
            balance = float(account.get('available_balance', {}).get('value', 0))
            account_type = account.get('type', 'UNKNOWN')
            
            if balance > 0.01:
                if currency == 'USD':
                    usd_balance += balance
                    total_cash += balance
                    print(f'  💵 USD: ${balance:.2f} (Type: {account_type})')
                elif currency == 'USDC':
                    usdc_balance += balance
                    total_cash += balance
                    print(f'  💵 USDC: ${balance:.2f} (Type: {account_type})')
                elif currency not in ['USD', 'USDC', 'USDT']:
                    # Crypto position
                    try:
                        product = client.get_product(f'{currency}-USD')
                        price = float(product.get('price', 0))
                        value_usd = balance * price
                        
                        # Try to get 24h change
                        stats = client.get_product_book(f'{currency}-USD', limit=1)
                        
                        positions.append({
                            'currency': currency,
                            'balance': balance,
                            'price': price,
                            'value_usd': value_usd
                        })
                        print(f'  🪙 {currency}: {balance:.8f} @ ${price:.4f} = ${value_usd:.2f}')
                    except Exception as e:
                        print(f'  🪙 {currency}: {balance:.8f} (price unavailable)')
        
        total_position_value = sum(p['value_usd'] for p in positions)
        total_portfolio = total_cash + total_position_value
        
        print()
        print('='*80)
        print('📊 PORTFOLIO SUMMARY:')
        print('='*80)
        print(f'  Available Cash: ${total_cash:.2f}')
        print(f'    - USD:  ${usd_balance:.2f}')
        print(f'    - USDC: ${usdc_balance:.2f}')
        print()
        print(f'  Open Positions: ${total_position_value:.2f}')
        print(f'    - {len(positions)} crypto position(s)')
        print()
        print(f'  📈 TOTAL PORTFOLIO VALUE: ${total_portfolio:.2f}')
        print('='*80)
        
        # Trading status
        print()
        print('='*80)
        print('🤖 TRADING STATUS:')
        print('='*80)
        
        if total_cash >= 5.0:
            print(f'  ✅ READY TO TRADE')
            print(f'  ✅ Trading from: Coinbase Advanced Trade')
            print(f'  ✅ Available cash: ${total_cash:.2f}')
            print(f'  ✅ Can execute orders')
        else:
            print(f'  ⚠️  WARNING: Low balance')
            print(f'  ⚠️  Available: ${total_cash:.2f}')
            print(f'  ⚠️  Minimum recommended: $5.00')
            print()
            print('  📝 To add funds:')
            print('     1. Go to Coinbase Advanced Trade')
            print('     2. Deposit funds to your portfolio')
            print('     3. Funds are available immediately')
        
        # Goal tracking
        if total_portfolio > 0:
            print()
            print('='*80)
            print('🎯 GOAL TRACKING:')
            print('='*80)
            goal = 5000
            current = total_portfolio
            remaining = goal - current
            percent_complete = (current / goal) * 100
            
            print(f'  Current Balance: ${current:.2f}')
            print(f'  Target Goal: ${goal:.2f}')
            print(f'  Remaining: ${remaining:.2f}')
            print(f'  Progress: {percent_complete:.2f}%')
            print()
            if remaining > 0:
                days_left = 15  # Based on README goal
                daily_return_needed = ((goal / current) ** (1 / days_left) - 1) * 100
                print(f'  📊 To reach ${goal:.2f} in {days_left} days:')
                print(f'     Required daily return: {daily_return_needed:.2f}%')
        
        print('='*80)
        print()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
