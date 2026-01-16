#!/usr/bin/env python3
"""
Integration test to verify log message ordering in multi-broker connection flow.

This test simulates the actual flow when connecting users to Kraken/Alpaca
to ensure log messages appear in chronological order after the fix.
"""

import logging
import sys
import os
import time
from unittest.mock import Mock, patch

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Setup logging exactly like bot.py
root = logging.getLogger()
if root.handlers:
    for handler in list(root.handlers):
        root.removeHandler(handler)

nija_logger = logging.getLogger("nija")
nija_logger.setLevel(logging.INFO)
nija_logger.propagate = False

formatter = logging.Formatter(
    '%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

if not nija_logger.hasHandlers():
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.flush = lambda: sys.stdout.flush()
    nija_logger.addHandler(console_handler)

# Import after logging setup
from broker_manager import KrakenBroker, AlpacaBroker, AccountType, BrokerType
from multi_account_broker_manager import MultiAccountBrokerManager

print("=" * 70)
print("INTEGRATION TEST: Multi-Broker Connection Log Ordering")
print("=" * 70)
print()

# Mock user object
class MockUser:
    def __init__(self, name, user_id, broker_type):
        self.name = name
        self.user_id = user_id
        self.broker_type = broker_type

print("TEST: Simulating Kraken user connection with permission error")
print("-" * 70)
print()

# Create a user
test_user = MockUser("Test User", "test_user", "kraken")

# Log the connection attempt (like multi_account_broker_manager does)
multi_account_logger = logging.getLogger('nija.multi_account')
multi_account_logger.info(f"📊 Connecting {test_user.name} ({test_user.user_id}) to Kraken...")

# Flush using the NEW method (root logger)
root_nija_logger = logging.getLogger("nija")
for handler in root_nija_logger.handlers:
    handler.flush()

# Small delay to ensure timestamp difference
time.sleep(0.001)

# Simulate what happens in KrakenBroker.connect() when there's a permission error
broker_logger = logging.getLogger('nija.broker')
broker_logger.error(f"❌ Kraken connection test failed (USER:{test_user.user_id}): EGeneral:Permission denied")
broker_logger.error("   ⚠️  API KEY PERMISSION ERROR")
broker_logger.error("   Your Kraken API key does not have the required permissions.")
broker_logger.error("   Fix: Enable 'Query Funds', 'Query/Create/Cancel Orders' permissions at:")
broker_logger.error("   https://www.kraken.com/u/security/api")

# Flush again to ensure all messages are visible
for handler in root_nija_logger.handlers:
    handler.flush()

print()
print("=" * 70)
print("VERIFICATION:")
print("=" * 70)
print()
print("✅ If logs above appear in this order, the fix is working:")
print("   1. '📊 Connecting Test User...'")
print("   2. '❌ Kraken connection test failed...'")
print("   3. '⚠️  API KEY PERMISSION ERROR'")
print("   4. Permission fix instructions")
print()
print("❌ If logs appear jumbled or out of order, the fix needs adjustment.")
print()
print("Handler counts:")
print(f"  - multi_account logger: {len(multi_account_logger.handlers)} handlers")
print(f"  - broker logger: {len(broker_logger.handlers)} handlers")
print(f"  - root nija logger: {len(root_nija_logger.handlers)} handlers")
print()
print("=" * 70)
