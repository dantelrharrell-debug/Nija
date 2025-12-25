#!/usr/bin/env python3
"""
AUTO LIQUIDATE - NO CONFIRMATION REQUIRED
Immediately sells ALL crypto to stop bleeding
"""
import os
import sys
from coinbase.rest import RESTClient
import time

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
    print("🚨 AUTO LIQUIDATION - SELLING ALL CRYPTO NOW")
    print("="*80)
    
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    
    if not api_key or not api_secret:
        print("\n❌ Missing API credentials")
        return 1
    
    try:
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        
        print("\n🔍 Finding crypto positions...")
        accounts = client.get_accounts()
        
        # Handle response format
        if isinstance(accounts, dict):
            account_list = accounts.get('accounts', [])
        elif hasattr(accounts, 'accounts'):
            account_list = accounts.accounts
        else:
            account_list = []
        
        positions_to_sell = []
        
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
            
            # Skip USD, USDC and zero balances
            if currency in ['USD', 'USDC'] or available < 0.00000001:
                continue
            
            positions_to_sell.append({
                'currency': currency,
                'amount': available
            })
        
        if not positions_to_sell:
            print("\n✅ No crypto positions to sell")
            return 0
        
        print(f"\n📊 Found {len(positions_to_sell)} positions:")
        for i, pos in enumerate(positions_to_sell, 1):
            print(f"  {i}. {pos['currency']}: {pos['amount']:.8f}")
        
        print(f"\n🔴 SELLING ALL {len(positions_to_sell)} POSITIONS...")
        print("="*80)
        
        sold = 0
        failed = 0
        total_usd = 0.0
        
        for i, pos in enumerate(positions_to_sell, 1):
            currency = pos['currency']
            amount = pos['amount']
            symbol = f"{currency}-USD"
            
            print(f"\n[{i}/{len(positions_to_sell)}] Selling {currency}...")
            
            try:
                # Create market sell order
                order = client.market_order_sell(
                    client_order_id=f"emergency_sell_{currency}_{int(time.time())}",
                    product_id=symbol,
                    base_size=str(amount)
                )
                
                # Check result
                if order and (hasattr(order, 'success') or isinstance(order, dict)):
                    success = order.get('success', True) if isinstance(order, dict) else getattr(order, 'success', True)
                    
                    if success:
                        print(f"  ✅ SOLD {currency}!")
                        sold += 1
                    else:
                        error_message = order.get('error_message', 'Unknown') if isinstance(order, dict) else getattr(order, 'error_message', 'Unknown')
                        print(f"  ❌ Failed: {error_message}")
                        failed += 1
                else:
                    print(f"  ❌ No response")
                    failed += 1
                
                time.sleep(0.3)  # Rate limit protection
                
            except Exception as e:
                print(f"  ❌ Exception: {e}")
                failed += 1
        
        print("\n" + "="*80)
        print("📊 LIQUIDATION COMPLETE")
        print("="*80)
        print(f"  ✅ Sold: {sold}/{len(positions_to_sell)}")
        print(f"  ❌ Failed: {failed}")
        
        # Check final balance
        print("\n🔍 Checking final balance...")
        time.sleep(2)
        
        accounts = client.get_accounts()
        if isinstance(accounts, dict):
            account_list = accounts.get('accounts', [])
        elif hasattr(accounts, 'accounts'):
            account_list = accounts.accounts
        else:
            account_list = []
        
        usd_balance = 0.0
        for account in account_list:
            if isinstance(account, dict):
                currency = account.get('currency', '')
                available = float(account.get('available_balance', {}).get('value', 0))
            else:
                currency = getattr(account, 'currency', '')
                if hasattr(account, 'available_balance'):
                    if isinstance(account.available_balance, dict):
                        available = float(account.available_balance.get('value', 0))
                    else:
                        available = float(getattr(account.available_balance, 'value', 0))
                else:
                    available = 0.0
            
            if currency == 'USD':
                usd_balance = available
                break
        
        print(f"\n💰 Final Cash Balance: ${usd_balance:.2f}")
        print("="*80 + "\n")
        
        return 0 if failed == 0 else 1
        
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
