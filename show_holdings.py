#!/usr/bin/env python3
"""
Show all crypto holdings and their current value
"""
import os
from coinbase.rest import RESTClient

# Load .env
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

def main():
    print("\n" + "="*80)
    print("💰 YOUR CRYPTO HOLDINGS - Where Your $59.48 Went")
    print("="*80)
    
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    
    if not api_key or not api_secret:
        print("\n❌ Missing credentials")
        return
    
    try:
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        
        print("\n📊 Fetching all account balances...")
        accounts = client.get_accounts()
        
        # Handle dict or object response
        if isinstance(accounts, dict):
            account_list = accounts.get('accounts', [])
        elif hasattr(accounts, 'accounts'):
            account_list = accounts.accounts
        else:
            account_list = []
        
        usd_balance = 0.0
        crypto_holdings = []
        total_usd_value = 0.0
        
        print("\n" + "="*80)
        print("HOLDINGS BREAKDOWN")
        print("="*80)
        
        for account in account_list:
            # Handle dict or object
            if isinstance(account, dict):
                currency = account.get('currency', 'UNKNOWN')
                available = float(account.get('available_balance', {}).get('value', 0))
            else:
                currency = getattr(account, 'currency', 'UNKNOWN')
                if hasattr(account, 'available_balance'):
                    if isinstance(account.available_balance, dict):
                        available = float(account.available_balance.get('value', 0))
                    else:
                        available = float(getattr(account.available_balance, 'value', 0))
                else:
                    available = 0.0
            
            if currency == 'USD':
                usd_balance = available
                print(f"\n💵 USD Balance: ${available:.2f}")
                continue
            
            if available > 0.00000001:  # Has crypto
                # Get current price
                try:
                    product_id = f"{currency}-USD"
                    ticker = client.get_product(product_id)
                    
                    if isinstance(ticker, dict):
                        price = float(ticker.get('price', 0))
                    else:
                        price = float(getattr(ticker, 'price', 0))
                    
                    value_usd = available * price
                    total_usd_value += value_usd
                    
                    crypto_holdings.append({
                        'currency': currency,
                        'amount': available,
                        'price': price,
                        'value': value_usd
                    })
                except:
                    # Can't get price, still show holding
                    crypto_holdings.append({
                        'currency': currency,
                        'amount': available,
                        'price': 0,
                        'value': 0
                    })
        
        if crypto_holdings:
            print(f"\n🪙 CRYPTO HOLDINGS ({len(crypto_holdings)} assets):")
            print("-" * 80)
            print(f"{'Asset':<10} {'Amount':<20} {'Price':<15} {'Value (USD)':<15}")
            print("-" * 80)
            
            for holding in sorted(crypto_holdings, key=lambda x: x['value'], reverse=True):
                currency = holding['currency']
                amount = holding['amount']
                price = holding['price']
                value = holding['value']
                
                if price > 0:
                    print(f"{currency:<10} {amount:<20.8f} ${price:<14.4f} ${value:<14.2f}")
                else:
                    print(f"{currency:<10} {amount:<20.8f} {'N/A':<15} {'N/A':<15}")
        else:
            print("\n   ℹ️  No crypto holdings found")
        
        # Summary
        print("\n" + "="*80)
        print("📊 SUMMARY")
        print("="*80)
        
        print(f"\n💵 USD Balance:        ${usd_balance:.2f}")
        print(f"🪙 Crypto Value:       ${total_usd_value:.2f}")
        print(f"💰 Total Portfolio:    ${usd_balance + total_usd_value:.2f}")
        
        print(f"\n📉 Money Lost:")
        print(f"   Spent on trades:    $63.67")
        print(f"   Current value:      ${usd_balance + total_usd_value:.2f}")
        print(f"   Loss:               ${63.67 - (usd_balance + total_usd_value):.2f}")
        
        # Recommendations
        print("\n" + "="*80)
        print("💡 WHAT TO DO")
        print("="*80)
        
        if crypto_holdings:
            print("\nOption 1: SELL ALL CRYPTO → Recover partial funds")
            print("   Run: python3 sell_all_positions.py")
            print(f"   Will recover: ~${total_usd_value:.2f}")
            
            print("\nOption 2: HOLD → Wait for prices to recover")
            print("   Risk: Prices may drop further")
            print("   Upside: Prices may rise and reduce loss")
            
            print("\nOption 3: DEPOSIT $50 → Continue trading properly")
            print("   With more capital, bot can manage these positions")
            print("   Can scale out winners, cut losers")
        else:
            print("\n✅ No crypto to sell - all positions already closed")
        
        print("\n⚠️  CRITICAL: Stop depositing $5")
        print("   Each $5 deposit will repeat this cycle")
        print("   Minimum viable deposit: $50-100")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
