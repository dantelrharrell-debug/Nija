#!/usr/bin/env python3
"""
DIAGNOSE WHY NIJA ISN'T SELLING YOUR 8+ HOLDINGS
Checks position detection and sell logic
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from trading_strategy import TradingStrategy
import logging

logging.basicConfig(level=logging.WARNING)  # Suppress INFO logs for cleaner output
logger = logging.getLogger(__name__)

def main():
    print("=" * 80)
    print("🔍 DIAGNOSING NIJA SELL ISSUE")
    print("=" * 80)
    
    # Initialize trading strategy (same as bot does)
    print("\n1️⃣ Initializing NIJA Trading Strategy (same as bot)...")
    print("   This will connect to Coinbase and load positions...")
    strategy = TradingStrategy()
    broker = strategy.broker
    
    # Check what NIJA sees
    print("\n2️⃣ Checking what NIJA sees...")
    print(f"\n   📊 NIJA's open_positions: {len(strategy.open_positions)} positions")
    if strategy.open_positions:
        print("\n   Tracked positions:")
        for symbol, pos in strategy.open_positions.items():
            entry = pos.get('entry_price', 0)
            side = pos.get('side', '?')
            size_usd = pos.get('size_usd', 0)
            stop = pos.get('stop_loss', 0)
            tp = pos.get('take_profit', 0)
            print(f"      • {symbol}: {side} @ ${entry:.2f} | Size: ${size_usd:.2f}")
            print(f"        Stop: ${stop:.2f} | TP: ${tp:.2f}")
    else:
        print("      ⚠️  NIJA shows NO OPEN POSITIONS!")
    
    # Check balance
    print("\n3️⃣ Checking account balance...")
    balance = broker.get_account_balance()
    trading_balance = balance.get('trading_balance', 0)
    consumer_usdc = balance.get('consumer_usdc', 0)
    consumer_usd = balance.get('consumer_usd', 0)
    crypto = balance.get('crypto', {})
    
    print(f"\n   💵 Advanced Trade USD/USDC: ${trading_balance:.2f}")
    print(f"   💵 Consumer USDC: ${consumer_usdc:.2f}")
    print(f"   💵 Consumer USD: ${consumer_usd:.2f}")
    
    if crypto:
        print(f"\n   🪙 Crypto holdings ({len(crypto)} found):")
        for coin, amount in crypto.items():
            print(f"      • {coin}: {amount:.8f}")
    else:
        print(f"\n   🪙 Crypto holdings: None")
    
    # Check position files
    print("\n4️⃣ Checking position tracking files...")
    position_files = [
        "/usr/src/app/data/open_positions.json",
        "./data/open_positions.json",
        "/workspaces/Nija/data/open_positions.json"
    ]
    
    found_file = False
    for filepath in position_files:
        if os.path.exists(filepath):
            import json
            with open(filepath, 'r') as f:
                saved_positions = json.load(f)
            print(f"\n   ✅ Found: {filepath}")
            print(f"      Saved positions: {len(saved_positions)}")
            if saved_positions:
                for symbol, data in saved_positions.items():
                    print(f"         • {symbol}: ${data.get('entry_price', 0):.2f}")
            found_file = True
            break
    
    if not found_file:
        print("\n   ❌ No position tracking file found!")
    
    # DIAGNOSIS
    print("\n" + "=" * 80)
    print("🔬 DIAGNOSIS:")
    print("=" * 80)
    
    num_crypto = len(crypto)
    num_tracked = len(strategy.open_positions)
    
    if num_crypto > 0 and num_tracked == 0:
        print("\n❌ CRITICAL ISSUE DETECTED:")
        print(f"   Coinbase shows {num_crypto} crypto holdings")
        print(f"   BUT NIJA is tracking {num_tracked} positions")
        print("\n   ROOT CAUSE: Position tracking is broken!")
        print("\n   POSSIBLE REASONS:")
        print("      1. Holdings are in Consumer wallet (API can't trade them)")
        print("      2. Bot was restarted and lost position memory")
        print("      3. Holdings were bought outside of NIJA")
        print("      4. Position tracking file is missing/corrupted")
        print("\n   SOLUTION:")
        if trading_balance == 0 and (consumer_usd > 0 or consumer_usdc > 0):
            print("      ⚠️  Your funds are in CONSUMER WALLET!")
            print(f"         Consumer has: ${consumer_usd + consumer_usdc:.2f}")
            print(f"         Advanced Trade has: ${trading_balance:.2f}")
            print("\n      👉 TRANSFER FUNDS TO ADVANCED TRADE:")
            print("         1. Go to: https://www.coinbase.com/advanced-portfolio")
            print("         2. Click 'Deposit' → 'From Coinbase'")
            print("         3. Transfer funds to Advanced Trade")
            print("\n      ⚠️  CRYPTO IN CONSUMER WALLET CANNOT BE SOLD VIA API")
            print("         You must manually sell on Coinbase.com")
        else:
            print("      • Manually sell crypto on Coinbase.com")
            print("      • Or restart bot after transferring to Advanced Trade")
    
    elif num_crypto > 0 and num_tracked > 0:
        print("\n⚠️  PARTIAL TRACKING:")
        print(f"   Coinbase shows {num_crypto} crypto holdings")
        print(f"   NIJA is tracking {num_tracked} positions")
        
        if num_crypto > num_tracked:
            print(f"\n   {num_crypto - num_tracked} holdings are NOT being tracked!")
            print("   These may have been bought outside NIJA or tracking was lost")
        
        if trading_balance == 0:
            print("\n   ⚠️  WARNING: $0 Advanced Trade balance!")
            print("      Bot CANNOT execute sells without balance for fees")
            print("      Transfer at least $10 to Advanced Trade for fees")
        else:
            print("\n   ✅ NIJA should be attempting to sell tracked positions")
            print("      Check if prices are hitting stop-loss/take-profit targets")
    
    elif num_crypto == 0:
        print("\n✅ No crypto holdings found")
        print("   Nothing to sell!")
    
    print("\n" + "=" * 80)
    print("\n💡 KEY INSIGHT:")
    print("   NIJA can ONLY sell positions it knows about (tracked in memory)")
    print("   AND that are in the Advanced Trade portfolio")
    print("   Consumer wallet crypto is invisible to the API")
    print("=" * 80)

if __name__ == "__main__":
    main()
