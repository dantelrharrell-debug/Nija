"""
Example usage of the safe trading stack.
This demonstrates how to use safe_order.submit_order() for all trading operations.
"""

import os
import sys

# Set up environment for demo
os.environ['MODE'] = 'DRY_RUN'  # Change to 'LIVE' with proper setup for real trading
os.environ['MAX_ORDER_USD'] = '100.0'
os.environ['MAX_ORDERS_PER_MINUTE'] = '5'
os.environ['MANUAL_APPROVAL_COUNT'] = '2'  # First 2 orders require manual approval
os.environ['LOG_PATH'] = '/tmp/nija_demo_trading.log'

# For LIVE mode, you would also need:
# os.environ['MODE'] = 'LIVE'
# os.environ['COINBASE_ACCOUNT_ID'] = 'your-account-id'
# os.environ['CONFIRM_LIVE'] = 'true'

from nija_client import CoinbaseClient
import safe_order


def demo_safe_order():
    """Demonstrate safe order submission."""
    print("\n" + "="*60)
    print("Safe Trading Stack Demo")
    print("="*60 + "\n")
    
    print(f"Current MODE: {os.environ['MODE']}")
    print(f"MAX_ORDER_USD: ${os.environ['MAX_ORDER_USD']}")
    print(f"MAX_ORDERS_PER_MINUTE: {os.environ['MAX_ORDERS_PER_MINUTE']}")
    print(f"MANUAL_APPROVAL_COUNT: {os.environ['MANUAL_APPROVAL_COUNT']}")
    print(f"LOG_PATH: {os.environ['LOG_PATH']}\n")
    
    # Initialize client (this will run safety checks)
    print("Initializing CoinbaseClient...")
    try:
        client = CoinbaseClient()
        print("✓ Client initialized successfully\n")
    except Exception as e:
        print(f"✗ Failed to initialize client: {e}\n")
        return
    
    # Example 1: Submit a valid order
    print("Example 1: Submit a valid order (DRY_RUN)")
    try:
        result = safe_order.submit_order(
            client=client,
            symbol="BTC-USD",
            side="buy",
            size_usd=50.0
        )
        print(f"✓ Order result: {result}\n")
    except Exception as e:
        print(f"✗ Order failed: {e}\n")
    
    # Example 2: Submit another order (will require approval due to MANUAL_APPROVAL_COUNT=2)
    print("Example 2: Submit second order (will require manual approval)")
    try:
        result = safe_order.submit_order(
            client=client,
            symbol="ETH-USD",
            side="buy",
            size_usd=30.0
        )
        print(f"✓ Order result: {result}\n")
    except Exception as e:
        print(f"✗ Order failed: {e}\n")
    
    # Example 3: Try to exceed MAX_ORDER_USD
    print("Example 3: Try to exceed MAX_ORDER_USD (should fail)")
    try:
        result = safe_order.submit_order(
            client=client,
            symbol="BTC-USD",
            side="buy",
            size_usd=150.0  # Exceeds $100 limit
        )
        print(f"Order result: {result}")
    except ValueError as e:
        print(f"✓ Order correctly rejected: {e}\n")
    except Exception as e:
        print(f"✗ Unexpected error: {e}\n")
    
    # Example 4: Check pending approvals
    print("Example 4: Check pending approvals")
    pending = safe_order.get_pending_approvals()
    print(f"Pending orders: {len(pending['pending'])}")
    print(f"Approved orders: {len(pending['approved'])}")
    
    if pending['pending']:
        print("\nPending orders requiring approval:")
        for order in pending['pending']:
            print(f"  - Order ID: {order['order_id']}")
            print(f"    Symbol: {order['symbol']}, Side: {order['side']}, Size: ${order['size_usd']}")
    
    # Example 5: Approve a pending order
    if pending['pending']:
        print(f"\nExample 5: Approve first pending order")
        first_order = pending['pending'][0]
        order_id = first_order['order_id']
        
        approved = safe_order.approve_order(order_id)
        if approved:
            print(f"✓ Order {order_id} approved")
        else:
            print(f"✗ Failed to approve order {order_id}")
    
    # Show audit log location
    print(f"\n📝 Check audit log at: {os.environ['LOG_PATH']}")
    print(f"📋 Check pending approvals at: {safe_order.get_pending_approvals_path()}")
    
    print("\n" + "="*60)
    print("Demo completed!")
    print("="*60 + "\n")


if __name__ == '__main__':
    demo_safe_order()
