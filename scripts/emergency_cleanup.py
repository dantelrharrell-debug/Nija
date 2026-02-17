#!/usr/bin/env python3
"""
Emergency Cleanup Script
========================
Performs immediate cleanup of trading account to free capital and remove distortions:

1. Cancel ALL open orders (free held capital)
2. Force liquidate dust positions (< $1.00 USD)
3. Purge invalid symbols from internal state (e.g., AUT-USD)

This script is designed for immediate execution when:
- Capital is tied up in stale orders
- Dust positions are distorting P&L tracking
- Invalid symbols are causing errors

Usage:
    python scripts/emergency_cleanup.py [--broker kraken|coinbase] [--dry-run]

Options:
    --broker    Specify broker (default: kraken)
    --dry-run   Show what would be done without executing

Author: NIJA Trading Bot
Date: 2026-02-17
"""

import os
import sys
import argparse
import time
from datetime import datetime

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bot'))

# Import broker adapters
from broker_integration import KrakenBrokerAdapter
from broker_dust_cleanup import BrokerDustCleanup

# Constants
DUST_THRESHOLD_USD = 1.00  # Positions below this are considered dust


def print_banner(message: str):
    """Print a formatted banner message."""
    print("\n" + "=" * 80)
    print(f"  {message}")
    print("=" * 80 + "\n")


def get_all_open_orders(adapter) -> list:
    """
    Get all open orders from broker.
    
    Returns:
        List of open order dictionaries
    """
    try:
        if hasattr(adapter, '_kraken_api_call'):
            # Kraken-specific implementation
            result = adapter._kraken_api_call('OpenOrders')
            
            if result and 'result' in result:
                open_orders = result['result'].get('open', {})
                orders = []
                
                for order_id, order in open_orders.items():
                    descr = order.get('descr', {})
                    orders.append({
                        'order_id': order_id,
                        'pair': descr.get('pair', 'UNKNOWN'),
                        'type': descr.get('type', 'UNKNOWN'),
                        'ordertype': descr.get('ordertype', 'UNKNOWN'),
                        'volume': float(order.get('vol', 0)),
                        'vol_exec': float(order.get('vol_exec', 0)),
                        'status': order.get('status', 'unknown')
                    })
                
                return orders
        
        # Generic implementation (if broker has get_open_orders method)
        if hasattr(adapter, 'get_open_orders'):
            return adapter.get_open_orders()
        
        return []
    
    except Exception as e:
        print(f"❌ Error fetching open orders: {e}")
        return []


def cancel_all_orders(adapter, dry_run: bool = False) -> tuple:
    """
    Cancel all open orders.
    
    Args:
        adapter: Broker adapter instance
        dry_run: If True, only show what would be cancelled
    
    Returns:
        Tuple of (success_count, fail_count)
    """
    print_banner("STEP 1: Cancel All Open Orders")
    
    orders = get_all_open_orders(adapter)
    
    if not orders:
        print("✅ No open orders found - nothing to cancel")
        return (0, 0)
    
    print(f"📋 Found {len(orders)} open order(s):")
    for order in orders:
        order_id_display = order['order_id'][:12] + '...' if len(order['order_id']) > 12 else order['order_id']
        print(f"   • {order['pair']}: {order['type']} {order['volume']:.8f} ({order['ordertype']}) - ID: {order_id_display}")
    
    if dry_run:
        print("\n🔍 DRY RUN: Would cancel all orders listed above")
        return (len(orders), 0)
    
    print("\n🔴 Cancelling all orders...")
    success_count = 0
    fail_count = 0
    
    for order in orders:
        order_id = order['order_id']
        order_id_display = order_id[:12] + '...' if len(order_id) > 12 else order_id
        try:
            success = adapter.cancel_order(order_id)
            if success:
                print(f"   ✅ Cancelled: {order['pair']} (ID: {order_id_display})")
                success_count += 1
            else:
                print(f"   ❌ Failed to cancel: {order['pair']} (ID: {order_id_display})")
                fail_count += 1
            
            # Rate limiting: small delay between cancellations
            time.sleep(0.1)
        
        except Exception as e:
            print(f"   ❌ Error cancelling {order['pair']}: {e}")
            fail_count += 1
    
    print(f"\n📊 Cancellation Summary: {success_count} succeeded, {fail_count} failed")
    return (success_count, fail_count)


def liquidate_dust_positions(adapter, dry_run: bool = False) -> dict:
    """
    Force liquidate all dust positions using BrokerDustCleanup.
    
    Args:
        adapter: Broker adapter instance
        dry_run: If True, only show what would be liquidated
    
    Returns:
        Dict with cleanup statistics
    """
    print_banner("STEP 2: Force Liquidate Dust Positions")
    
    # Initialize dust cleanup engine
    dust_cleanup = BrokerDustCleanup(
        dust_threshold_usd=DUST_THRESHOLD_USD,
        dry_run=dry_run
    )
    
    # Run cleanup
    results = dust_cleanup.cleanup_all_dust(adapter)
    
    return results


def purge_invalid_symbols() -> int:
    """
    Purge invalid symbols (like AUT-USD) from internal state files.
    
    Returns:
        Number of symbols purged
    """
    print_banner("STEP 3: Purge Invalid Symbols from Internal State")
    
    # Symbols to purge (already in restricted_symbols.json)
    invalid_symbols = ['AUT-USD', 'AUTUSD']
    purged_count = 0
    
    # Check positions.json files
    positions_files = [
        'data/positions.json',
        '.nija_trading_state.json',
    ]
    
    for filepath in positions_files:
        if not os.path.exists(filepath):
            continue
        
        try:
            import json
            
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            # Check if any invalid symbols are tracked
            found_invalid = False
            
            if isinstance(data, dict):
                if 'positions' in data:
                    positions = data['positions']
                    for symbol in invalid_symbols:
                        if symbol in positions:
                            print(f"   🗑️  Found {symbol} in {filepath}")
                            del positions[symbol]
                            found_invalid = True
                            purged_count += 1
            
            if found_invalid:
                # Write back cleaned data
                with open(filepath, 'w') as f:
                    json.dump(data, f, indent=2)
                print(f"   ✅ Cleaned {filepath}")
        
        except Exception as e:
            print(f"   ⚠️  Error processing {filepath}: {e}")
    
    if purged_count == 0:
        print("✅ No invalid symbols found in internal state")
        print(f"   (Checked: {', '.join(invalid_symbols)})")
    else:
        print(f"\n✅ Purged {purged_count} invalid symbol reference(s)")
    
    return purged_count


def verify_cleanup(adapter) -> bool:
    """
    Verify that cleanup was successful.
    
    Returns:
        True if account is clean, False otherwise
    """
    print_banner("STEP 4: Verify Cleanup")
    
    # Check open orders
    orders = get_all_open_orders(adapter)
    orders_clean = len(orders) == 0
    
    if orders_clean:
        print("✅ Open orders: 0")
    else:
        print(f"⚠️  WARNING: {len(orders)} open order(s) still remain")
    
    # Check balance info
    try:
        balance_info = adapter.get_account_balance()
        if not balance_info.get('error'):
            total = balance_info.get('total_balance', 0)
            print(f"💰 Current balance: ${total:.2f}")
    except Exception as e:
        print(f"⚠️  Could not fetch balance: {e}")
    
    if orders_clean:
        print("\n" + "=" * 80)
        print("  ✅ CLEANUP SUCCESSFUL")
        print("  • All open orders cancelled (capital freed)")
        print("  • Dust positions liquidated (accounting clean)")
        print("  • Invalid symbols purged (state clean)")
        print("=" * 80 + "\n")
        return True
    else:
        print("\n⚠️  Cleanup incomplete - manual review recommended")
        return False


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Emergency cleanup: cancel orders, liquidate dust, purge invalid symbols'
    )
    parser.add_argument(
        '--broker',
        choices=['kraken', 'coinbase'],
        default='kraken',
        help='Broker to clean up (default: kraken)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without executing'
    )
    args = parser.parse_args()
    
    print_banner("EMERGENCY CLEANUP")
    
    if args.dry_run:
        print("🔍 DRY RUN MODE: No actual changes will be made\n")
    
    # Get API credentials based on broker
    if args.broker == 'kraken':
        api_key = os.getenv('KRAKEN_API_KEY') or os.getenv('KRAKEN_PLATFORM_API_KEY')
        api_secret = os.getenv('KRAKEN_API_SECRET') or os.getenv('KRAKEN_PLATFORM_API_SECRET')
        
        if not api_key or not api_secret:
            print("❌ ERROR: Kraken API credentials not found")
            print("\nPlease set environment variables:")
            print("  - KRAKEN_API_KEY or KRAKEN_PLATFORM_API_KEY")
            print("  - KRAKEN_API_SECRET or KRAKEN_PLATFORM_API_SECRET")
            sys.exit(1)
        
        print("🔗 Connecting to Kraken...")
        adapter = KrakenBrokerAdapter(api_key=api_key, api_secret=api_secret)
    
    else:  # coinbase
        print("❌ ERROR: Coinbase adapter not yet implemented in this script")
        print("Please use --broker kraken")
        sys.exit(1)
    
    if not adapter.connect():
        print(f"❌ Failed to connect to {args.broker.title()} API")
        sys.exit(1)
    
    print(f"✅ Connected to {args.broker.title()}\n")
    
    # Execute cleanup steps
    try:
        # Step 1: Cancel all open orders
        cancel_success, cancel_fail = cancel_all_orders(adapter, dry_run=args.dry_run)
        
        # Step 2: Force liquidate dust positions
        dust_results = liquidate_dust_positions(adapter, dry_run=args.dry_run)
        
        # Step 3: Purge invalid symbols (always runs, no dry-run)
        if not args.dry_run:
            purged = purge_invalid_symbols()
        else:
            print_banner("STEP 3: Purge Invalid Symbols (Skipped in Dry Run)")
        
        if args.dry_run:
            print_banner("DRY RUN COMPLETE")
            print("No actual changes were made.")
            print("\nTo execute the cleanup, run without --dry-run flag:")
            print(f"  python scripts/emergency_cleanup.py --broker {args.broker}")
            return
        
        # Small delay for operations to settle
        if cancel_success > 0 or dust_results.get('closed', 0) > 0:
            print("\n⏳ Waiting 5 seconds for operations to settle...")
            time.sleep(5)
        
        # Step 4: Verify cleanup
        success = verify_cleanup(adapter)
        
        sys.exit(0 if success else 1)
    
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
