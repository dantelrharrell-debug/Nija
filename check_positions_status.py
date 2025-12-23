#!/usr/bin/env python3
"""
Check current positions on Coinbase
"""

import os
from coinbase.rest import RESTClient

def check_positions():
    """Check all current positions"""
    
    print("\n" + "="*60)
    print("📊 CURRENT POSITIONS CHECK")
    print("="*60 + "\n")
    
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    
    if not api_key or not api_secret:
        print("❌ Missing API credentials")
        return
    
    try:
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        
        print("📡 Fetching accounts...")
        accounts_response = client.get_accounts()
        accounts = accounts_response.get('accounts', [])
        
        print(f"✅ Found {len(accounts)} accounts\n")
        
        # Track totals
        total_usd = 0.0
        total_crypto_value = 0.0
        positions = []
        
        for account in accounts:
            currency = account.get('currency', '')
            balance_value = account.get('available_balance', {}).get('value', '0')
            balance = float(balance_value)
            
            if balance <= 0:
                continue
            
            if currency == 'USD':
                total_usd = balance
                print(f"💵 USD Balance: ${balance:.2f}")
            else:
                # Crypto position
                if balance > 0.00001:  # Skip dust
                    positions.append({
                        'currency': currency,
                        'balance': balance
                    })
                    print(f"💰 {currency}: {balance:.8f}")
        
        print(f"\n{'='*60}")
        print(f"📊 SUMMARY")
        print(f"{'='*60}")
        print(f"💵 USD Cash: ${total_usd:.2f}")
        print(f"💰 Open Positions: {len(positions)}")
        
        if positions:
            print(f"\n⚠️  YOU HAVE {len(positions)} OPEN POSITIONS:")
            for p in positions:
                print(f"   - {p['currency']}: {p['balance']:.8f}")
            print(f"\n🚨 These positions are BLEEDING if they're losing")
            print(f"   Run: python emergency_close_all_positions.py")
        else:
            print("\n✅ No open positions - account is clean")
        
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    check_positions()
