#!/usr/bin/env python3
"""
Check current liquidation status on Coinbase.
Shows how many crypto positions are still open after emergency liquidation trigger.
"""
import os
import json
from dotenv import load_dotenv
from coinbase.rest import RESTClient

load_dotenv()

# Initialize client
try:
    client = RESTClient(
        api_key=os.getenv('COINBASE_API_KEY'),
        api_secret=os.getenv('COINBASE_API_SECRET'),
        api_key_cert_path=os.getenv('COINBASE_PEM_CONTENT', '')
    )
    print("✅ Connected to Coinbase API\n")
except Exception as e:
    print(f"❌ Failed to connect: {e}")
    exit(1)

try:
    # Get portfolio breakdown
    print("📊 Fetching portfolio status...\n")
    breakdown = client.get_portfolio_breakdown()
    
    # Extract spot positions
    positions = []
    if 'spot_positions' in breakdown:
        for pos in breakdown['spot_positions']:
            asset = pos.get('asset', {})
            asset_name = asset.get('name', 'UNKNOWN')
            
            # Skip fiat
            if asset_name in ['US Dollar', 'USD Coin']:
                continue
                
            available = float(pos.get('available_to_trade', {}).get('value', 0))
            fiat_value = float(pos.get('available_to_trade_fiat', {}).get('value', 0))
            
            if available > 0 or fiat_value > 0:
                positions.append({
                    'symbol': f"{asset_name}-USD",
                    'quantity': available,
                    'fiat_value': fiat_value
                })
    
    if positions:
        print(f"⚠️  {len(positions)} CRYPTO POSITIONS STILL OPEN:\n")
        total_value = 0
        for i, pos in enumerate(positions, 1):
            print(f"  [{i}] {pos['symbol']}: {pos['quantity']:.8f} ≈ ${pos['fiat_value']:.2f}")
            total_value += pos['fiat_value']
        print(f"\n   💰 Total crypto value: ${total_value:.2f}")
    else:
        print("✅ NO CRYPTO POSITIONS OPEN - Liquidation appears to be complete!")
    
    # Check USD balance
    print("\n" + "="*60)
    if 'spot_positions' in breakdown:
        for pos in breakdown['spot_positions']:
            asset = pos.get('asset', {})
            asset_name = asset.get('name', 'UNKNOWN')
            if asset_name == 'US Dollar':
                usd_available = float(pos.get('available_to_trade', {}).get('value', 0))
                print(f"💵 USD Available: ${usd_available:.2f}")
    
    # Check if trigger file still exists
    trigger_file = '/workspaces/Nija/LIQUIDATE_ALL_NOW.conf'
    if os.path.exists(trigger_file):
        print(f"⚠️  Trigger file still exists: {trigger_file}")
        print("   → Bot may still be processing liquidation")
    else:
        print("✅ Trigger file removed (liquidation cycle completed)")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
