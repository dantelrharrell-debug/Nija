#!/usr/bin/env python3
"""
Demo script showing the safe trading stack in action

This demonstrates all the safety features:
1. DRY_RUN mode (default)
2. LIVE mode requirements
3. Rate limiting
4. Order size limits
5. Manual approval workflow
6. Audit logging
"""

import os
import sys
import time

# Set up environment for demo
os.environ['MODE'] = 'DRY_RUN'
os.environ['MAX_ORDER_USD'] = '100.0'
os.environ['MAX_ORDERS_PER_MINUTE'] = '5'
os.environ['LOG_PATH'] = '/tmp/nija_demo_orders.log'
os.environ['TRADINGVIEW_WEBHOOK_SECRET'] = 'demo_secret_key'

print("=" * 70)
print("NIJA SAFE TRADING STACK DEMO")
print("=" * 70)
print()

# Demo 1: Import and initialize
print("1️⃣  Initializing CoinbaseClient with safety checks...")
print("-" * 70)

from nija_client import CoinbaseClient, check_live_safety

print(f"MODE: {os.environ.get('MODE')}")
check_live_safety()
print()

# Demo 2: Safe order submission
print("2️⃣  Submitting safe orders through safe_order module...")
print("-" * 70)

from safe_order import submit_order

# Mock client for demo
class MockClient:
    def place_order(self, symbol, side, size_usd):
        return {'status': 'filled', 'order_id': 'demo-12345'}

client = MockClient()

# Submit some orders
orders = [
    ('BTC-USD', 'buy', 50.0),
    ('ETH-USD', 'buy', 30.0),
    ('SOL-USD', 'sell', 20.0),
]

for symbol, side, size in orders:
    result = submit_order(client, symbol, side, size)
    print(f"  {side.upper()} ${size} {symbol} -> {result['status']}: {result.get('message', '')}")

print()

# Demo 3: Rate limiting
print("3️⃣  Testing rate limiting...")
print("-" * 70)

# Reset rate limiting by using a fresh import with unique log path
os.environ['LOG_PATH'] = '/tmp/nija_demo_ratelimit.log'
if 'safe_order' in sys.modules:
    del sys.modules['safe_order']

from safe_order import submit_order as submit_order_fresh

for i in range(5):
    result = submit_order_fresh(client, 'BTC-USD', 'buy', 10.0)
    print(f"  Order {i+1}: {result['status']}")

try:
    result = submit_order_fresh(client, 'BTC-USD', 'buy', 10.0)
    print(f"  ❌ Rate limit not enforced!")
except RuntimeError as e:
    print(f"  ✅ Rate limit enforced: {e}")

print()

# Demo 4: Order size limit
print("4️⃣  Testing order size limit (max $100)...")
print("-" * 70)

try:
    result = submit_order(client, 'BTC-USD', 'buy', 150.0)
    print(f"  ❌ Size limit not enforced!")
except ValueError as e:
    print(f"  ✅ Size limit enforced: {e}")

print()

# Demo 5: LIVE mode safety
print("5️⃣  Testing LIVE mode safety requirements...")
print("-" * 70)

os.environ['MODE'] = 'LIVE'
os.environ['COINBASE_ACCOUNT_ID'] = ''
os.environ['CONFIRM_LIVE'] = 'false'

# Reload modules
if 'config' in sys.modules:
    del sys.modules['config']
if 'nija_client' in sys.modules:
    del sys.modules['nija_client']

from nija_client import check_live_safety as check_live_v2

try:
    check_live_v2()
    print("  ❌ LIVE mode safety not enforced!")
except RuntimeError as e:
    print(f"  ✅ LIVE mode safety enforced:")
    print(f"     {e}")

print()

# Demo 6: Audit log
print("6️⃣  Checking audit log...")
print("-" * 70)

log_path = '/tmp/nija_demo_orders.log'
if os.path.exists(log_path):
    import json
    with open(log_path, 'r') as f:
        entries = [json.loads(line) for line in f]
    
    print(f"  ✅ Found {len(entries)} audit log entries")
    print(f"  📁 Log location: {log_path}")
    
    if entries:
        print(f"\n  Latest entry:")
        latest = entries[-1]
        print(f"    Timestamp: {latest['timestamp']}")
        print(f"    Mode: {latest['mode']}")
        print(f"    Request: {latest['request']['side']} {latest['request']['symbol']} ${latest['request']['size_usd']}")
        print(f"    Response: {latest['response']['status']}")
else:
    print("  ⚠️  No audit log found")

print()
print("=" * 70)
print("DEMO COMPLETE ✅")
print("=" * 70)
print()
print("Key Takeaways:")
print("  • DRY_RUN mode prevents real orders by default")
print("  • LIVE mode requires explicit account ID + confirmation")
print("  • Rate limiting prevents excessive order submission")
print("  • Order size limits prevent oversized trades")
print("  • All orders are logged for audit trail")
print()
print("See SAFE_TRADING_STACK.md for complete documentation")
print()
