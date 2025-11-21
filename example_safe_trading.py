#!/usr/bin/env python3
"""
Example: Safe Trading with Nija

This example demonstrates how to use the safe trading stack.
"""

import os

# Set environment variables for testing
os.environ['MODE'] = 'DRY_RUN'
os.environ['MAX_ORDER_USD'] = '50.0'
os.environ['MAX_ORDERS_PER_MINUTE'] = '3'

from nija_client import CoinbaseClient
from safe_order import submit_order


def main():
    print("=" * 60)
    print("Safe Trading Example - DRY_RUN Mode")
    print("=" * 60)
    
    # Initialize client (safety checks run automatically)
    print("\n1. Initializing CoinbaseClient...")
    try:
        client = CoinbaseClient()
        print("   ✅ Client initialized successfully")
    except RuntimeError as e:
        print(f"   ❌ Failed to initialize: {e}")
        return
    
    # Example 1: Submit a valid order
    print("\n2. Submitting a valid order (BTC-USD, $10)...")
    try:
        response = submit_order(
            client,
            symbol='BTC-USD',
            side='buy',
            size_usd=10.0
        )
        print(f"   ✅ Order submitted: {response['status']}")
    except Exception as e:
        print(f"   ❌ Order failed: {e}")
    
    # Example 2: Try to submit an order that exceeds limit
    print("\n3. Submitting an order that exceeds MAX_ORDER_USD ($100)...")
    try:
        response = submit_order(
            client,
            symbol='ETH-USD',
            side='buy',
            size_usd=100.0
        )
        print(f"   ✅ Order submitted: {response['status']}")
    except RuntimeError as e:
        print(f"   ❌ Order rejected (as expected): {str(e)[:60]}...")
    
    # Example 3: Submit multiple orders to test rate limiting
    print("\n4. Testing rate limiting (3 orders per minute limit)...")
    for i in range(4):
        try:
            response = submit_order(
                client,
                symbol=f'BTC-USD',
                side='buy',
                size_usd=5.0
            )
            print(f"   Order {i+1}: {response['status']}")
        except RuntimeError as e:
            print(f"   Order {i+1}: ❌ Rejected - {str(e)[:50]}...")
    
    print("\n" + "=" * 60)
    print("Example completed!")
    print("=" * 60)
    print("\nNote: All orders were in DRY_RUN mode - no real trades executed")
    print("Check 'trade_audit.log' for audit trail\n")


if __name__ == '__main__':
    main()
