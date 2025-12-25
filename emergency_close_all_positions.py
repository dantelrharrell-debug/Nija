#!/usr/bin/env python3
"""
EMERGENCY: Close all open positions immediately
"""

import os
import sys
from coinbase.rest import RESTClient
import json
import time

def emergency_close_all():
    """Close all positions on Coinbase immediately"""
    
    print("\n" + "="*60)
    print("🚨 EMERGENCY POSITION CLOSER")
    print("="*60 + "\n")
    
    # Get API credentials
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    
    if not api_key or not api_secret:
        print("❌ ERROR: Missing API credentials")
        print("   Set COINBASE_API_KEY and COINBASE_API_SECRET")
        return False
    
    try:
        # Initialize Coinbase client
        print("📡 Connecting to Coinbase...")
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        
        # Get all accounts
        print("📊 Fetching all accounts...")
        accounts_response = client.get_accounts()
        accounts = getattr(accounts_response, 'accounts', [])
        
        print(f"\n✅ Found {len(accounts)} accounts\n")
        
        # Find all crypto holdings (excluding USD)
        holdings = []
        total_value_usd = 0.0
        
        for account in accounts:
            currency = account.get('currency', '')
            balance = float(account.get('available_balance', {}).get('value', 0))
            
            # Skip USD and zero balances
            if currency == 'USD' or balance <= 0:
                continue
            
            # Skip very small amounts (dust)
            if balance < 0.00001:
                continue
            
            holdings.append({
                'currency': currency,
                'balance': balance,
                'account': account
            })
            
            print(f"💰 {currency}: {balance:.8f}")
        
        if not holdings:
            print("\n✅ No positions to close - account is clean")
            return True
        
        print(f"\n📋 Total holdings to liquidate: {len(holdings)}")
        print("\n⚠️  WARNING: This will sell ALL crypto positions immediately")
        print("    Continuing in 3 seconds...")
        
        time.sleep(3)
        
        # Sell each holding
        closed_count = 0
        failed_count = 0
        
        for holding in holdings:
            currency = holding['currency']
            balance = holding['balance']
            symbol = f"{currency}-USD"
            
            print(f"\n🔄 Attempting to close {symbol}...")
            
            try:
                # Create market sell order
                order = client.market_order_sell(
                    client_order_id=f"emergency_close_{currency}_{int(time.time())}",
                    product_id=symbol,
                    base_size=str(balance)
                )
                
                if order:
                    print(f"   ✅ CLOSED: {symbol} ({balance:.8f} {currency})")
                    print(f"      Order ID: {order.get('order_id', 'N/A')}")
                    closed_count += 1
                else:
                    print(f"   ❌ FAILED: No order response for {symbol}")
                    failed_count += 1
                    
            except Exception as e:
                error_msg = str(e)
                print(f"   ❌ ERROR closing {symbol}: {error_msg}")
                failed_count += 1
            
            # Rate limiting
            time.sleep(0.5)
        
        # Summary
        print("\n" + "="*60)
        print("📊 LIQUIDATION SUMMARY")
        print("="*60)
        print(f"✅ Successfully closed: {closed_count}")
        print(f"❌ Failed to close: {failed_count}")
        print(f"📋 Total processed: {len(holdings)}")
        print("="*60 + "\n")
        
        # Update local position file
        positions_file = "data/open_positions.json"
        if os.path.exists(positions_file):
            with open(positions_file, 'w') as f:
                json.dump({
                    "timestamp": str(time.time()),
                    "positions": {},
                    "count": 0
                }, f, indent=2)
            print("💾 Cleared local positions file\n")
        
        return closed_count > 0
        
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = emergency_close_all()
    sys.exit(0 if success else 1)
