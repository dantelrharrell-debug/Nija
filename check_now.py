#!/usr/bin/env python3
"""Quick balance check with .env loading"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()
print("✅ Loaded .env file")

# Now import and run
import sys
sys.path.insert(0, '/workspaces/Nija')

from bot.broker_manager import CoinbaseBroker
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

def main():
    print("\n" + "="*70)
    print("🔍 NIJA BALANCE DIAGNOSTIC - WITH $100+ DEPOSIT")
    print("="*70 + "\n")
    
    broker = CoinbaseBroker()
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        print("\nCredential check:")
        print(f"  API_KEY: {'✅' if os.getenv('COINBASE_API_KEY') else '❌'}")
        print(f"  API_SECRET: {'✅' if os.getenv('COINBASE_API_SECRET') else '❌'}")
        return
    
    print("\n✅ Connected to Coinbase API\n")
    
    # Get balances
    balance_info = broker.get_account_balance()
    
    print("\n" + "="*70)
    print("📊 CURRENT BALANCE:")
    print("="*70)
    print(f"Consumer USD (v2 API):        ${balance_info.get('consumer_usd', 0):.2f} [NOT TRADABLE]")
    print(f"Consumer USDC (v2 API):       ${balance_info.get('consumer_usdc', 0):.2f} [NOT TRADABLE]")
    print(f"Advanced Trade USD (v3 API):  ${balance_info.get('usd', 0):.2f} [TRADABLE ✅]")
    print(f"Advanced Trade USDC (v3 API): ${balance_info.get('usdc', 0):.2f} [TRADABLE ✅]")
    print()
    print(f"🎯 TOTAL TRADING BALANCE: ${balance_info.get('trading_balance', 0):.2f}")
    print("="*70)
    
    trading_balance = balance_info.get('trading_balance', 0)
    consumer_total = balance_info.get('consumer_usd', 0) + balance_info.get('consumer_usdc', 0)
    total_all = trading_balance + consumer_total
    
    print(f"\n💰 TOTAL ACROSS ALL ACCOUNTS: ${total_all:.2f}")
    
    # Goal analysis
    print("\n" + "="*70)
    print("🎯 GOAL ASSESSMENT:")
    print("="*70)
    
    if total_all >= 100:
        print(f"✅ YOU HAVE ${total_all:.2f} - GOAL IS ACHIEVABLE!")
        print("\nNext steps:")
        if consumer_total > 0:
            print(f"  1. Transfer ${consumer_total:.2f} from Consumer to Advanced Trade")
            print("  2. Start trading with proper risk management")
        else:
            print("  1. ✅ Funds are in Advanced Trade - ready to trade!")
            print(f"  2. With ${trading_balance:.2f}, you can reach your goal")
        
        # Calculate what's needed
        if trading_balance >= 100:
            print(f"\n🚀 READY TO TRADE: ${trading_balance:.2f} available")
            print("\nPossible with CONSERVATIVE trading:")
            print(f"  - Starting capital: ${trading_balance:.2f}")
            print("  - Target: Grow to desired amount")
            print("  - Strategy: APEX V7.1 with strict risk management")
            print("  - Realistic timeframe: Depends on market conditions")
        else:
            print(f"\n⚠️ Need to transfer ${consumer_total:.2f} to start trading")
    else:
        print(f"❌ Current total: ${total_all:.2f}")
        print(f"   Need: ${100 - total_all:.2f} more to reach $100")
    
    # Check for any crypto holdings
    print("\n" + "="*70)
    print("🪙 CHECKING CRYPTO POSITIONS...")
    print("="*70)
    
    try:
        positions = broker.get_positions()
        if positions:
            total_crypto_value = 0
            print("\nCurrent crypto positions:")
            for pos in positions:
                value = pos.get('market_value', 0)
                total_crypto_value += value
                print(f"  {pos.get('symbol', 'Unknown')}: ${value:.2f}")
            print(f"\nTotal crypto value: ${total_crypto_value:.2f}")
            print(f"Combined with cash: ${total_all + total_crypto_value:.2f}")
        else:
            print("\n✅ No crypto positions - all funds in cash")
    except Exception as e:
        print(f"\n⚠️ Could not check positions: {e}")

if __name__ == "__main__":
    main()
