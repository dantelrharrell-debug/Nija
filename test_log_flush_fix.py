#!/usr/bin/env python3
"""
Test script to verify log message ordering fix.

This simulates the logging pattern used in multi_account_broker_manager.py
to ensure messages from different loggers appear in the correct order.
"""

import logging
import sys
import time

# Setup logging like bot.py
root = logging.getLogger()
if root.handlers:
    for handler in list(root.handlers):
        root.removeHandler(handler)

# Get nija logger
nija_logger = logging.getLogger("nija")
nija_logger.setLevel(logging.INFO)
nija_logger.propagate = False

# Single formatter
formatter = logging.Formatter(
    '%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Add console handler
if not nija_logger.hasHandlers():
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.flush = lambda: sys.stdout.flush()
    nija_logger.addHandler(console_handler)

# Create child loggers like the actual code
multi_account_logger = logging.getLogger('nija.multi_account')
broker_logger = logging.getLogger('nija.broker')

print("=" * 70)
print("TESTING LOG MESSAGE ORDERING")
print("=" * 70)
print()

print("TEST 1: OLD METHOD (flushing child logger handlers - BROKEN)")
print("-" * 70)

# Simulate old code - this won't flush anything
multi_account_logger.info("📊 Connecting Test User to Kraken... (OLD METHOD)")
for handler in multi_account_logger.handlers:  # This is empty!
    handler.flush()

# Simulate broker connection logs (from different logger)
time.sleep(0.001)  # Small delay to ensure different timestamps
broker_logger.error("❌ Kraken connection test failed: Permission denied (OLD METHOD)")

print()
print("TEST 2: NEW METHOD (flushing root nija logger - FIXED)")
print("-" * 70)

# Simulate new code - this will flush properly
multi_account_logger.info("📊 Connecting Test User to Kraken... (NEW METHOD)")
root_nija_logger = logging.getLogger("nija")
for handler in root_nija_logger.handlers:
    handler.flush()

# Simulate broker connection logs
time.sleep(0.001)  # Small delay
broker_logger.error("❌ Kraken connection test failed: Permission denied (NEW METHOD)")

# Flush again to ensure all messages are visible
for handler in root_nija_logger.handlers:
    handler.flush()

print()
print("=" * 70)
print("ANALYSIS:")
print("=" * 70)
print()
print("In both tests above, you should see:")
print("  1. 'Connecting Test User...' message FIRST")
print("  2. 'connection test failed' message SECOND")
print()
print("If messages appear out of order, the flush is not working correctly.")
print()
print(f"Child logger handlers count: {len(multi_account_logger.handlers)}")
print(f"Root nija logger handlers count: {len(root_nija_logger.handlers)}")
print()
print("The NEW METHOD explicitly flushes the root 'nija' logger's handlers,")
print("ensuring all child logger messages (multi_account, broker, etc.) are")
print("written immediately in the correct order.")
print("=" * 70)
