#!/usr/bin/env python3
"""
EMERGENCY: Sell all crypto positions to recover funds
"""
import os
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
    print("🚨 EMERGENCY POSITION LIQUIDATOR")
    print("="*80)
    print("\n⚠️  WARNING: This will sell ALL your crypto holdings!")
    print("You will recover whatever USD value they currently have.")
    
    confirm = input("\nType 'SELL ALL' to proceed: ")
    
    if confirm != 'SELL ALL':
        print("\n❌ Cancelled - no positions sold")
        return
    
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    
    if not api_key or not api_secret:
        print("\n❌ Missing credentials")
        return
    
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
            
            # Skip USD and zero balances
            if currency == 'USD' or available < 0.00000001:
                continue
            
            positions_to_sell.append({
                'currency': currency,
                'amount': available
            })
        
        if not positions_to_sell:
            print("\n✅ No crypto positions to sell")
            return
        
        print(f"\n📊 Found {len(positions_to_sell)} positions to sell:")
        for pos in positions_to_sell:
            print(f"   • {pos['currency']}: {pos['amount']:.8f}")
        
        print("\n🔄 Selling positions...")
        print("="*80)
        
        total_recovered = 0.0
        successful = 0
        failed = 0
        
        for pos in positions_to_sell:
            currency = pos['currency']
            amount = pos['amount']
            product_id = f"{currency}-USD"
            
            try:
                print(f"\n🔴 Selling {currency}...")
                print(f"   Amount: {amount:.8f}")
                
                # Place market sell order
                import uuid
                order = client.market_order_sell(
                    client_order_id=str(uuid.uuid4()),
                    product_id=product_id,
                    base_size=str(amount)
                )
                
                # Check order status
                if isinstance(order, dict):
                    success = order.get('success', False)
                    order_id = order.get('order_id', 'UNKNOWN')
                else:
                    success = getattr(order, 'success', False)
                    order_id = getattr(order, 'order_id', 'UNKNOWN')
                
                if success:
                    # Try to get fill price
                    time.sleep(1)  # Wait for order to fill
                    
                    try:
                        order_details = client.get_order(order_id)
                        
                        if isinstance(order_details, dict):
                            filled_value = float(order_details.get('filled_value', 0))
                        else:
                            filled_value = float(getattr(order_details, 'filled_value', 0))
                        
                        total_recovered += filled_value
                        print(f"   ✅ SOLD for ${filled_value:.2f}")
                        successful += 1
                    except:
                        print(f"   ✅ SOLD (couldn't get exact value)")
                        successful += 1
                else:
                    print(f"   ❌ Sale failed")
                    failed += 1
                
                time.sleep(0.5)  # Rate limit protection
                
            except Exception as e:
                print(f"   ❌ Error: {e}")
                failed += 1
        
        # Summary
        print("\n\n" + "="*80)
        print("📊 LIQUIDATION COMPLETE")
        print("="*80)
        
        print(f"\n✅ Successful: {successful}/{len(positions_to_sell)}")
        print(f"❌ Failed:     {failed}/{len(positions_to_sell)}")
        print(f"\n💵 USD Recovered: ~${total_recovered:.2f}")
        
        # Check new balance
        print("\n🔍 Checking final balance...")
        accounts = client.get_accounts()
        
        if isinstance(accounts, dict):
            account_list = accounts.get('accounts', [])
        elif hasattr(accounts, 'accounts'):
            account_list = accounts.accounts
        else:
            account_list = []
        
        for account in account_list:
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
                print(f"\n💰 Final USD Balance: ${available:.2f}")
                break
        
        print("\n" + "="*80)
        print("💡 NEXT STEPS")
        print("="*80)
        print("\n1. ✅ Positions liquidated")
        print("2. 🛑 STOP depositing $5 (will repeat the cycle)")
        print("3. 💰 Deposit $50-100 if you want to continue trading")
        print("4. ⚙️  Update bot settings (run: python3 fix_bot_settings.py)")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
