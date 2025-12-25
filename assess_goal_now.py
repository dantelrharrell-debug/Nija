#!/usr/bin/env python3
"""
COMPREHENSIVE GOAL ASSESSMENT - Check balance, connection, and determine if goal is achievable
"""
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

sys.path.insert(0, '/workspaces/Nija')

from bot.broker_manager import CoinbaseBroker
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

def main():
    print("\n" + "="*80)
    print("🎯 NIJA GOAL ASSESSMENT - $100+ DEPOSIT CHECK")
    print("="*80 + "\n")
    
    # Initialize broker
    broker = CoinbaseBroker()
    
    # Test connection
    print("🔌 Testing Coinbase connection...")
    if not broker.connect():
        print("\n❌ CONNECTION FAILED!")
        print("\nTroubleshooting:")
        print("  1. Check that .env file exists")
        print("  2. Verify COINBASE_API_KEY is set")
        print("  3. Verify COINBASE_API_SECRET is set")
        return False
    
    print("✅ Connected to Coinbase API successfully!\n")
    
    # Get balances
    print("💰 Fetching account balances...")
    balance_info = broker.get_account_balance()
    
    consumer_usd = balance_info.get('consumer_usd', 0)
    consumer_usdc = balance_info.get('consumer_usdc', 0)
    advanced_usd = balance_info.get('usd', 0)
    advanced_usdc = balance_info.get('usdc', 0)
    trading_balance = balance_info.get('trading_balance', 0)
    
    consumer_total = consumer_usd + consumer_usdc
    total_cash = consumer_total + trading_balance
    
    print("\n" + "="*80)
    print("📊 CURRENT BALANCE BREAKDOWN:")
    print("="*80)
    print(f"\n💵 Consumer Wallet (v2 API - NOT for trading):")
    print(f"   - USD:  ${consumer_usd:.2f}")
    print(f"   - USDC: ${consumer_usdc:.2f}")
    print(f"   - Total: ${consumer_total:.2f}")
    
    print(f"\n🔄 Advanced Trade (v3 API - TRADING ACCOUNT):")
    print(f"   - USD:  ${advanced_usd:.2f}")
    print(f"   - USDC: ${advanced_usdc:.2f}")
    print(f"   - Total: ${trading_balance:.2f}")
    
    print(f"\n💰 TOTAL CASH: ${total_cash:.2f}")
    print("="*80)
    
    # Check for crypto positions
    print("\n🪙 Checking for crypto positions...")
    try:
        positions = broker.get_positions()
        crypto_value = 0
        crypto_positions = []
        
        if positions:
            for pos in positions:
                symbol = pos.get('symbol', 'Unknown')
                quantity = pos.get('quantity', 0)
                market_value = pos.get('market_value', 0)
                
                if market_value > 0.01:  # Only count positions worth more than 1 cent
                    crypto_value += market_value
                    crypto_positions.append({
                        'symbol': symbol,
                        'quantity': quantity,
                        'value': market_value
                    })
        
        if crypto_positions:
            print(f"\n✅ Found {len(crypto_positions)} crypto position(s):")
            for pos in crypto_positions:
                print(f"   - {pos['symbol']}: {pos['quantity']:.8f} = ${pos['value']:.2f}")
            print(f"\n   Total Crypto Value: ${crypto_value:.2f}")
        else:
            print("   No crypto positions found")
        
        total_value = total_cash + crypto_value
        
    except Exception as e:
        print(f"   ⚠️ Could not fetch positions: {e}")
        total_value = total_cash
        crypto_value = 0
        crypto_positions = []
    
    # GOAL ASSESSMENT
    print("\n" + "="*80)
    print("🎯 GOAL ASSESSMENT:")
    print("="*80)
    
    print(f"\n💵 Total Cash:   ${total_cash:.2f}")
    print(f"🪙 Crypto Value: ${crypto_value:.2f}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"💰 TOTAL VALUE:  ${total_value:.2f}")
    
    # Determine if goal is achievable
    if total_value >= 100:
        print(f"\n✅ YES! YOU HAVE ${total_value:.2f} - GOAL IS ACHIEVABLE!")
        print("\n" + "="*80)
        print("📋 ACTION PLAN:")
        print("="*80)
        
        # If crypto needs to be sold
        if crypto_value > 0:
            print(f"\n1️⃣ SELL CRYPTO POSITIONS (${crypto_value:.2f}):")
            print("   Run: python sell_all_crypto_now.py")
            print(f"   This will convert crypto to ${total_cash + crypto_value:.2f} cash")
        
        # If funds in consumer wallet
        if consumer_total > 0:
            print(f"\n2️⃣ TRANSFER FROM CONSUMER TO ADVANCED TRADE (${consumer_total:.2f}):")
            print("   - Go to Coinbase.com or app")
            print("   - Navigate to Advanced Trade")
            print("   - Transfer funds from Consumer to Advanced Trade")
            print("   - OR run deposit commands from Coinbase")
        
        # Trading readiness
        if trading_balance >= 100 or (trading_balance + crypto_value >= 100):
            print(f"\n3️⃣ START TRADING:")
            print(f"   ✅ You have ${trading_balance + crypto_value:.2f} ready for trading")
            print("   - Deploy APEX V7.1 strategy")
            print("   - Use conservative risk management")
            print("   - Target: Consistent growth")
        
        # Profitability analysis
        print("\n" + "="*80)
        print("📈 PROFITABILITY ANALYSIS:")
        print("="*80)
        
        tradable_amount = trading_balance + crypto_value
        
        if tradable_amount >= 100:
            print(f"\n💵 Starting Capital: ${tradable_amount:.2f}")
            print("\n✅ REALISTIC GOALS (Coinbase 2% fees):")
            print(f"   - Week 1:  ${tradable_amount * 1.05:.2f} (+5%)")
            print(f"   - Week 2:  ${tradable_amount * 1.10:.2f} (+10%)")
            print(f"   - Month 1: ${tradable_amount * 1.20:.2f} (+20%)")
            print(f"   - Month 3: ${tradable_amount * 1.50:.2f} (+50%)")
            
            print("\n⚠️ WARNING - Coinbase Fees:")
            print("   - 2-3% per trade")
            print("   - Need 4-6% profit per trade to break even")
            print("   - Consider Binance (0.1% fees) for better results")
            
            print("\n🎯 RECOMMENDED STRATEGY:")
            print("   - APEX V7.1 with strict risk management")
            print("   - Max 3-5% per position")
            print("   - Target 10-15% daily moves")
            print("   - Compound profits carefully")
            
        else:
            print(f"\n⚠️ Current tradable: ${tradable_amount:.2f}")
            print(f"   Need ${100 - tradable_amount:.2f} more in Advanced Trade to start")
        
    elif total_value >= 50:
        print(f"\n⚠️ YOU HAVE ${total_value:.2f} - GOAL IS CHALLENGING")
        print(f"\n   Need: ${100 - total_value:.2f} more to reach $100")
        print("\n   Options:")
        print(f"   1. Deposit ${100 - total_value:.2f} more (RECOMMENDED)")
        print("   2. Try to grow on Binance (0.1% fees)")
        print("   3. Risk it on Coinbase (low probability)")
        
    else:
        print(f"\n❌ YOU HAVE ${total_value:.2f} - GOAL NOT ACHIEVABLE ON COINBASE")
        print(f"\n   Why: Coinbase fees (2-3%) make growth from ${total_value:.2f} → $100 impossible")
        print(f"   Need: ${100 - total_value:.2f} more")
        print("\n   Recommendation:")
        print(f"   - Deposit ${100 - total_value:.2f} to reach $100")
        print("   - OR switch to Binance with 0.1% fees")
    
    print("\n" + "="*80)
    print("🔧 NEXT STEPS:")
    print("="*80)
    
    if crypto_positions:
        print("\n1. Sell crypto: python sell_all_crypto_now.py")
    if consumer_total > 0:
        print("2. Transfer to Advanced Trade (via Coinbase)")
    if trading_balance >= 100:
        print("3. Deploy trading bot: ./start.sh")
    
    print("\n" + "="*80)
    
    return True

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
