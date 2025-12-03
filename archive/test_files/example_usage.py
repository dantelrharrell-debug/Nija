#!/usr/bin/env python
"""
example_usage.py - Example usage of the safe trading stack

This script demonstrates how to use the safe trading stack with different modes.
"""

import os
import sys

# Set environment variables for this example
os.environ['MODE'] = 'DRY_RUN'
os.environ['MAX_ORDER_USD'] = '100'
os.environ['MAX_ORDERS_PER_MINUTE'] = '5'
os.environ['LOG_PATH'] = './example_orders.log'

# Import modules
from safe_order import submit_order, get_pending_orders, approve_pending_orders
from nija_client import CoinbaseClient

def example_dry_run():
    """Example: Using DRY_RUN mode to test without executing orders."""
    print("\n" + "="*60)
    print("EXAMPLE 1: DRY_RUN Mode")
    print("="*60)
    
    # Initialize client (performs safety checks)
    client = CoinbaseClient()
    
    # Submit a test order
    result = submit_order(
        client=client,
        symbol='BTC-USD',
        side='buy',
        size_usd=50.0,
        metadata={'source': 'example', 'strategy': 'TestStrategy'}
    )
    
    print(f"\nOrder result: {result}")
    print(f"Status: {result['status']}")
    print(f"Message: {result.get('message', 'N/A')}")


def example_manual_approval():
    """Example: Using manual approval for first N orders."""
    print("\n" + "="*60)
    print("EXAMPLE 2: Manual Approval")
    print("="*60)
    
    # Enable manual approval for first 2 orders
    os.environ['MANUAL_APPROVAL_COUNT'] = '2'
    
    # Reload modules to pick up new settings
    import importlib
    import config
    import safe_order
    importlib.reload(config)
    importlib.reload(safe_order)
    
    # Clear any existing approvals
    safe_order.clear_pending_orders()
    safe_order._order_timestamps = []
    
    client = CoinbaseClient()
    
    # First order - should be pending
    print("\n1. Submitting first order (should be pending)...")
    result1 = submit_order(client, 'BTC-USD', 'buy', 25.0)
    print(f"   Result: {result1['status']}")
    
    # Second order - should be pending
    print("\n2. Submitting second order (should be pending)...")
    result2 = submit_order(client, 'ETH-USD', 'buy', 30.0)
    print(f"   Result: {result2['status']}")
    
    # Check pending orders
    pending = get_pending_orders()
    print(f"\n3. Pending orders: {len(pending)}")
    for order in pending:
        print(f"   - {order['request']['side'].upper()} ${order['request']['size_usd']} {order['request']['symbol']}")
    
    # Approve orders
    print("\n4. Approving orders...")
    approve_pending_orders(count=2)
    
    # Third order - should go through
    print("\n5. Submitting third order (should execute)...")
    result3 = submit_order(client, 'SOL-USD', 'buy', 35.0)
    print(f"   Result: {result3['status']}")


def example_rate_limiting():
    """Example: Demonstrating rate limiting."""
    print("\n" + "="*60)
    print("EXAMPLE 3: Rate Limiting")
    print("="*60)
    
    # Set low rate limit for demonstration
    os.environ['MAX_ORDERS_PER_MINUTE'] = '3'
    os.environ['MANUAL_APPROVAL_COUNT'] = '0'
    
    # Reload modules
    import importlib
    import config
    import safe_order
    importlib.reload(config)
    importlib.reload(safe_order)
    
    # Clear rate limit tracking
    safe_order._order_timestamps = []
    
    client = CoinbaseClient()
    
    print(f"\nRate limit: {config.MAX_ORDERS_PER_MINUTE} orders per minute")
    
    # Submit orders up to the limit
    for i in range(3):
        print(f"\n{i+1}. Submitting order {i+1}...")
        result = submit_order(client, 'BTC-USD', 'buy', 10.0)
        print(f"   Status: {result['status']}")
    
    # Try to submit one more - should fail
    print("\n4. Attempting to exceed rate limit...")
    try:
        submit_order(client, 'BTC-USD', 'buy', 10.0)
        print("   ERROR: Should have been rate limited!")
    except RuntimeError as e:
        print(f"   ✅ Rate limit enforced: {str(e)[:50]}...")


def example_order_size_validation():
    """Example: Demonstrating order size validation."""
    print("\n" + "="*60)
    print("EXAMPLE 4: Order Size Validation")
    print("="*60)
    
    os.environ['MAX_ORDER_USD'] = '100'
    os.environ['MAX_ORDERS_PER_MINUTE'] = '10'
    os.environ['MANUAL_APPROVAL_COUNT'] = '0'
    
    # Reload modules
    import importlib
    import config
    import safe_order
    importlib.reload(config)
    importlib.reload(safe_order)
    
    # Clear tracking
    safe_order._order_timestamps = []
    
    client = CoinbaseClient()
    
    print(f"\nMax order size: ${config.MAX_ORDER_USD}")
    
    # Valid order
    print("\n1. Submitting valid order ($50)...")
    result = submit_order(client, 'BTC-USD', 'buy', 50.0)
    print(f"   Status: {result['status']}")
    
    # Invalid order (too large)
    print("\n2. Attempting to submit order exceeding limit ($150)...")
    try:
        submit_order(client, 'BTC-USD', 'buy', 150.0)
        print("   ERROR: Should have been rejected!")
    except ValueError as e:
        print(f"   ✅ Order rejected: {str(e)[:50]}...")


def main():
    """Run all examples."""
    print("\n" + "="*60)
    print("SAFE TRADING STACK - USAGE EXAMPLES")
    print("="*60)
    print("\nThese examples demonstrate the safe trading features:")
    print("- DRY_RUN mode")
    print("- Manual approval")
    print("- Rate limiting")
    print("- Order size validation")
    print("\nAll examples use DRY_RUN mode - no real orders will be placed.")
    print("="*60)
    
    try:
        example_dry_run()
        example_manual_approval()
        example_rate_limiting()
        example_order_size_validation()
        
        print("\n" + "="*60)
        print("ALL EXAMPLES COMPLETED SUCCESSFULLY")
        print("="*60)
        print("\nCheck example_orders.log for audit trail.")
        
    except Exception as e:
        print(f"\nError running examples: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
