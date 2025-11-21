#!/usr/bin/env python3
"""
Example: Using the Safe Trading Stack

This script demonstrates how to use the safe order module
for placing orders with all safety controls enabled.
"""

import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set safe defaults
os.environ.setdefault('MODE', 'DRY_RUN')
os.environ.setdefault('MAX_ORDER_USD', '100.0')
os.environ.setdefault('MAX_ORDERS_PER_MINUTE', '10')

from safe_order import safe_place_order, get_safe_order_manager
from nija_client import CoinbaseClient
from config import MODE, MAX_ORDER_USD, MAX_ORDERS_PER_MINUTE


def main():
    print("=" * 60)
    print("Safe Trading Stack Example")
    print("=" * 60)
    
    # Display current configuration
    print(f"\nConfiguration:")
    print(f"  MODE: {MODE}")
    print(f"  MAX_ORDER_USD: ${MAX_ORDER_USD}")
    print(f"  MAX_ORDERS_PER_MINUTE: {MAX_ORDERS_PER_MINUTE}")
    
    if MODE == "LIVE":
        print("\n⚠️  WARNING: LIVE MODE ENABLED - Real orders will be placed!")
        response = input("Are you sure you want to continue? (yes/no): ")
        if response.lower() != "yes":
            print("Aborted.")
            sys.exit(0)
    
    # Initialize client
    print("\nInitializing Coinbase client...")
    try:
        client = CoinbaseClient()
        print("✅ Client initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize client: {e}")
        sys.exit(1)
    
    # Example 1: Simple order
    print("\n" + "-" * 60)
    print("Example 1: Place a simple buy order")
    print("-" * 60)
    
    result = safe_place_order(
        client=client,
        symbol="BTC-USD",
        side="buy",
        size_usd=50.0,
        metadata={
            "strategy": "example_strategy",
            "note": "This is a test order"
        }
    )
    
    print(f"\nOrder result:")
    print(f"  Status: {result.get('status')}")
    print(f"  Order ID: {result.get('order_id')}")
    if result.get('mode'):
        print(f"  Mode: {result.get('mode')}")
    if result.get('error'):
        print(f"  Error: {result.get('error')}")
    
    # Example 2: Order that exceeds limits
    print("\n" + "-" * 60)
    print("Example 2: Attempt order that exceeds MAX_ORDER_USD")
    print("-" * 60)
    
    result = safe_place_order(
        client=client,
        symbol="ETH-USD",
        side="buy",
        size_usd=MAX_ORDER_USD + 50.0,  # Exceed limit
        metadata={"test": "exceeds_limit"}
    )
    
    print(f"\nOrder result:")
    print(f"  Status: {result.get('status')}")
    if result.get('error'):
        print(f"  Error: {result.get('error')}")
    
    # Example 3: Check pending approvals
    print("\n" + "-" * 60)
    print("Example 3: Check pending approvals")
    print("-" * 60)
    
    manager = get_safe_order_manager()
    pending = manager.get_pending_approvals()
    
    if pending:
        print(f"\nFound {len(pending)} pending approval(s):")
        for order in pending:
            print(f"  - {order['order_id']}: {order['side']} ${order['size_usd']} {order['symbol']}")
    else:
        print("\nNo pending approvals")
    
    # Example 4: Multiple orders to test rate limiting
    print("\n" + "-" * 60)
    print("Example 4: Test rate limiting (place multiple orders)")
    print("-" * 60)
    
    symbols = ["BTC-USD", "ETH-USD", "LTC-USD"]
    
    for i, symbol in enumerate(symbols, 1):
        print(f"\nOrder {i}/{len(symbols)}: {symbol}")
        result = safe_place_order(
            client=client,
            symbol=symbol,
            side="buy",
            size_usd=25.0,
            metadata={"batch": "rate_limit_test"}
        )
        print(f"  Status: {result.get('status')}")
        if result.get('error'):
            print(f"  Error: {result.get('error')}")
    
    print("\n" + "=" * 60)
    print("Examples complete!")
    print("=" * 60)
    
    # Show audit log location
    from config import LOG_PATH
    print(f"\nAudit log written to: {LOG_PATH}")
    print(f"View with: tail -f {LOG_PATH}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
