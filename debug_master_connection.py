#!/usr/bin/env python3
"""
Debug script to understand the Kraken master connection issue.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import BrokerType, AccountType, KrakenBroker
from multi_account_broker_manager import multi_account_broker_manager

print("="*70)
print("DEBUG: Testing Kraken Master Connection Status")
print("="*70)

# Simulate what trading_strategy.py does
print("\n1. Creating KrakenBroker instance with AccountType.MASTER")
kraken = KrakenBroker(account_type=AccountType.MASTER)
print(f"   Created: {kraken}")
print(f"   account_type: {kraken.account_type}")
print(f"   account_identifier: {kraken.account_identifier}")
print(f"   connected: {kraken.connected}")

print("\n2. Simulating successful connection (setting connected=True)")
kraken.connected = True
print(f"   connected: {kraken.connected}")

print("\n3. Registering in multi_account_manager.master_brokers")
multi_account_broker_manager.master_brokers[BrokerType.KRAKEN] = kraken
print(f"   Registered successfully")

print("\n4. Checking is_master_connected(BrokerType.KRAKEN)")
is_connected = multi_account_broker_manager.is_master_connected(BrokerType.KRAKEN)
print(f"   Result: {is_connected}")

print("\n5. Debugging why it might return False")
print(f"   BrokerType.KRAKEN in master_brokers: {BrokerType.KRAKEN in multi_account_broker_manager.master_brokers}")
if BrokerType.KRAKEN in multi_account_broker_manager.master_brokers:
    broker = multi_account_broker_manager.master_brokers[BrokerType.KRAKEN]
    print(f"   Broker from dict: {broker}")
    print(f"   Same instance? {broker is kraken}")
    print(f"   broker.connected: {broker.connected}")
    
print("\n6. Checking AccountType values")
print(f"   kraken.account_type: {kraken.account_type}")
print(f"   AccountType.MASTER: {AccountType.MASTER}")
print(f"   Equal? {kraken.account_type == AccountType.MASTER}")

print("\n" + "="*70)
print("DEBUG COMPLETE")
print("="*70)
