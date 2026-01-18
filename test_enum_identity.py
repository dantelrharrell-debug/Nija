#!/usr/bin/env python3
"""
Test if AccountType enum instances are the same across different imports.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

print("="*70)
print("Testing AccountType Enum Identity")
print("="*70)

# Import from different paths
try:
    from bot.broker_manager import AccountType as AccountType1
    print("\n1. Imported AccountType from bot.broker_manager")
    print(f"   {AccountType1}")
    print(f"   id: {id(AccountType1)}")
    print(f"   MASTER: {AccountType1.MASTER}")
    print(f"   MASTER id: {id(AccountType1.MASTER)}")
except ImportError as e:
    print(f"\n1. Failed to import from bot.broker_manager: {e}")
    AccountType1 = None

try:
    from broker_manager import AccountType as AccountType2
    print("\n2. Imported AccountType from broker_manager")
    print(f"   {AccountType2}")
    print(f"   id: {id(AccountType2)}")
    print(f"   MASTER: {AccountType2.MASTER}")
    print(f"   MASTER id: {id(AccountType2.MASTER)}")
except ImportError as e:
    print(f"\n2. Failed to import from broker_manager: {e}")
    AccountType2 = None

# Import from trading_strategy module
try:
    import trading_strategy
    if hasattr(trading_strategy, 'AccountType'):
        AccountType3 = trading_strategy.AccountType
        print("\n3. Got AccountType from trading_strategy module")
        print(f"   {AccountType3}")
        print(f"   id: {id(AccountType3)}")
        print(f"   MASTER: {AccountType3.MASTER}")
        print(f"   MASTER id: {id(AccountType3.MASTER)}")
    else:
        print("\n3. trading_strategy module doesn't have AccountType attribute")
        AccountType3 = None
except ImportError as e:
    print(f"\n3. Failed to import trading_strategy: {e}")
    AccountType3 = None

print("\n" + "="*70)
print("COMPARISON")
print("="*70)

if AccountType1 and AccountType2:
    print(f"\nAccountType1 is AccountType2: {AccountType1 is AccountType2}")
    print(f"AccountType1.MASTER == AccountType2.MASTER: {AccountType1.MASTER == AccountType2.MASTER}")

if AccountType1 and AccountType3:
    print(f"\nAccountType1 is AccountType3: {AccountType1 is AccountType3}")
    if AccountType1 is not AccountType3:
        print(f"AccountType1.MASTER == AccountType3.MASTER: {AccountType1.MASTER == AccountType3.MASTER}")
        print("⚠️  WARNING: Different enum classes! This will cause comparison failures!")

if AccountType2 and AccountType3:
    print(f"\nAccountType2 is AccountType3: {AccountType2 is AccountType3}")
    if AccountType2 is not AccountType3:
        print(f"AccountType2.MASTER == AccountType3.MASTER: {AccountType2.MASTER == AccountType3.MASTER}")
        print("⚠️  WARNING: Different enum classes! This will cause comparison failures!")

print("\n" + "="*70)
