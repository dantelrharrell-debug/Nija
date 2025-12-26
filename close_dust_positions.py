#!/usr/bin/env python3
"""
Close All Dust Positions (positions < $1.00)

This script will:
1. Identify all positions with USD value < $1.00
2. Force-sell them to free up position slots
3. Allow the bot to open more winning trades

Usage:
    python close_dust_positions.py [--dry-run] [--threshold 1.00]
"""

import os
import sys
import argparse
import time

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from coinbase.rest import RESTClient

# Default dust threshold: $1.00
DEFAULT_DUST_THRESHOLD = 1.00


def close_dust_positions(dry_run=False, threshold=DEFAULT_DUST_THRESHOLD):
    """
    Close all positions below the dust threshold
    
    Args:
        dry_run: If True, only show what would be closed without actually closing
        threshold: USD value threshold for dust (default: $1.00)
    """
    
    print("\n" + "="*70)
    print(f"🗑️  DUST POSITION CLEANUP (threshold: ${threshold:.2f})")
    print("="*70 + "\n")
    
    if dry_run:
        print("🔍 DRY RUN MODE - No actual trades will be executed\n")
    
    api_key = os.getenv("COINBASE_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET")
    
    if not api_key or not api_secret:
        print("❌ Missing API credentials")
        print("   Set COINBASE_API_KEY and COINBASE_API_SECRET environment variables")
        return False
    
    try:
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        
        print("📡 Fetching current positions...")
        accounts_response = client.get_accounts()
        accounts = accounts_response.get('accounts', [])
        
        print(f"✅ Found {len(accounts)} accounts\n")
        
        # Find dust positions
        dust_positions = []
        total_positions = 0
        usd_balance = 0.0
        
        for account in accounts:
            currency = account.get('currency', '')
            balance_value = account.get('available_balance', {}).get('value', '0')
            balance = float(balance_value)
            
            if balance <= 0:
                continue
            
            if currency == 'USD':
                usd_balance = balance
                continue
            
            # This is a crypto position
            symbol = f"{currency}-USD"
            try:
                product = client.get_product(symbol)
                price = float(product.price)
                usd_value = balance * price
                
                total_positions += 1
                
                # Check if this is dust
                if usd_value < threshold:
                    dust_positions.append({
                        'currency': currency,
                        'symbol': symbol,
                        'balance': balance,
                        'price': price,
                        'usd_value': usd_value
                    })
                    print(f"🗑️  DUST: {symbol:12s} ${usd_value:8.4f}  ({balance:.8f} @ ${price:.4f})")
                else:
                    print(f"✅  KEEP: {symbol:12s} ${usd_value:8.2f}  ({balance:.8f} @ ${price:.4f})")
                    
            except Exception as e:
                print(f"⚠️  ERROR getting price for {symbol}: {e}")
        
        print(f"\n{'='*70}")
        print(f"📊 SUMMARY")
        print(f"{'='*70}")
        print(f"💵 USD Cash:           ${usd_balance:.2f}")
        print(f"💰 Total Positions:    {total_positions}")
        print(f"🗑️  Dust (<${threshold:.2f}): {len(dust_positions)}")
        print(f"✅ Keep (≥${threshold:.2f}): {total_positions - len(dust_positions)}")
        
        if len(dust_positions) == 0:
            print(f"\n✅ No dust positions found! All positions are ≥ ${threshold:.2f}")
            print(f"{'='*70}\n")
            return True
        
        print(f"\n{'='*70}")
        print(f"🔥 CLOSING {len(dust_positions)} DUST POSITIONS")
        print(f"{'='*70}\n")
        
        closed_count = 0
        failed_count = 0
        total_value_freed = 0.0
        
        for i, pos in enumerate(dust_positions, 1):
            print(f"\n[{i}/{len(dust_positions)}] Closing {pos['symbol']}...")
            print(f"   Balance: {pos['balance']:.8f}")
            print(f"   Value:   ${pos['usd_value']:.4f}")
            
            if dry_run:
                print(f"   🔍 DRY RUN - Would sell {pos['balance']:.8f} {pos['currency']}")
                closed_count += 1
                total_value_freed += pos['usd_value']
                continue
            
            try:
                # Place market sell order
                order_config = {
                    "market_market_ioc": {
                        "base_size": str(pos['balance'])
                    }
                }
                
                result = client.create_order(
                    client_order_id=f"dust_cleanup_{int(time.time())}_{pos['currency']}",
                    product_id=pos['symbol'],
                    side="SELL",
                    order_configuration=order_config
                )
                
                print(f"   ✅ SOLD! Order ID: {result.get('order_id', 'N/A')}")
                closed_count += 1
                total_value_freed += pos['usd_value']
                
                # Rate limit to avoid API throttling
                time.sleep(0.5)
                
            except Exception as e:
                print(f"   ❌ FAILED to sell: {e}")
                failed_count += 1
        
        print(f"\n{'='*70}")
        print(f"✅ CLEANUP COMPLETE")
        print(f"{'='*70}")
        print(f"🗑️  Closed:  {closed_count} positions")
        print(f"❌ Failed:  {failed_count} positions")
        print(f"💰 Freed:   ${total_value_freed:.4f}")
        print(f"📈 Slots:   {closed_count} position slots now available")
        print(f"{'='*70}\n")
        
        if not dry_run and closed_count > 0:
            print("💡 Position slots freed! The bot can now open more winning trades.")
            print("   The 8-position limit will now count only positions ≥ $1.00\n")
        
        return closed_count > 0 or len(dust_positions) == 0
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Close dust positions to free up position slots',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would be closed
  python close_dust_positions.py --dry-run
  
  # Close all positions < $1.00
  python close_dust_positions.py
  
  # Close all positions < $5.00
  python close_dust_positions.py --threshold 5.00
        """
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be closed without actually closing anything'
    )
    
    parser.add_argument(
        '--threshold',
        type=float,
        default=DEFAULT_DUST_THRESHOLD,
        help=f'USD value threshold for dust (default: ${DEFAULT_DUST_THRESHOLD:.2f})'
    )
    
    args = parser.parse_args()
    
    success = close_dust_positions(dry_run=args.dry_run, threshold=args.threshold)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
