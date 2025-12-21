#!/usr/bin/env python3
"""
Diagnose current bot status:
1. What prices are the 9 positions at?
2. Are they above/below entry + above/below stop loss?
3. Are stops/takes being hit?
4. Why aren't positions closing if they should?
"""

import os
import sys
import time
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Add bot directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseBroker
from nija_apex_strategy_v71 import NIJAApexStrategyV71
import json

def main():
    print("\n" + "="*80)
    print("🔍 NIJA BOT STATUS DIAGNOSTIC")
    print("="*80)
    
    # Initialize broker
    broker = CoinbaseBroker()
    strategy = NIJAApexStrategyV71()
    
    # Get account balance
    print("\n1️⃣ ACCOUNT STATUS")
    print("-" * 80)
    try:
        accounts = broker.get_accounts()
        print(f"✅ Connected to Coinbase API")
        print(f"   Total accounts: {len(accounts)}")
        
        total_balance = 0
        crypto_positions = {}
        
        for account in accounts[:10]:  # Check first 10
            if account.get('available_balance', {}).get('value'):
                balance = float(account['available_balance']['value'])
                symbol = account['currency']
                crypto_positions[symbol] = balance
                total_balance += balance
        
        print(f"\n   Current Holdings:")
        for symbol, balance in sorted(crypto_positions.items(), key=lambda x: x[1], reverse=True):
            if balance > 0:
                print(f"   • {symbol}: {balance:.8f}")
        
        print(f"\n   Total USD Value: ${total_balance:.2f}")
    except Exception as e:
        print(f"❌ Error getting account: {e}")
        return
    
    # Check current prices vs entry prices
    print("\n\n2️⃣ POSITION ANALYSIS")
    print("-" * 80)
    
    holdings_symbols = {
        'BTC': {'entry': 19.73, 'amount': 0.000225},
        'ETH': {'entry': 25.61, 'amount': 0.008643},
        'DOGE': {'entry': 14.95, 'amount': 115.9},
        'SOL': {'entry': 10.96, 'amount': 0.088353},
        'XRP': {'entry': 10.31, 'amount': 5.428797},
        'LTC': {'entry': 9.75, 'amount': 0.128819},
        'HBAR': {'entry': 9.72, 'amount': 88},
        'BCH': {'entry': 9.59, 'amount': 0.016528},
        'ICP': {'entry': 9.23, 'amount': 3.0109},
    }
    
    total_entry_value = 0
    total_current_value = 0
    positions_to_close = []
    
    for symbol, entry_info in holdings_symbols.items():
        try:
            # Get current price
            ticker = broker.get_ticker(f"{symbol}-USD")
            current_price = float(ticker['price'])
            entry_price = entry_info['entry']
            amount = entry_info['amount']
            
            current_value = current_price * amount
            entry_value = entry_price * amount
            pnl = current_value - entry_value
            pnl_pct = (pnl / entry_value) * 100 if entry_value > 0 else 0
            
            total_entry_value += entry_value
            total_current_value += current_value
            
            # Check if positions should be closed
            stop_loss = entry_price * 0.98  # 2% stop loss
            take_profit = entry_price * 1.05  # 5% take profit
            
            status = ""
            if current_price <= stop_loss:
                status = "🔴 STOP LOSS HIT - SHOULD CLOSE"
                positions_to_close.append((symbol, 'stop_loss', current_price, pnl_pct))
            elif current_price >= take_profit:
                status = "🟢 TAKE PROFIT HIT - SHOULD CLOSE"
                positions_to_close.append((symbol, 'take_profit', current_price, pnl_pct))
            elif pnl_pct > 0:
                status = "📈 WINNING (no exit)"
            else:
                status = "📉 LOSING (no exit)"
            
            print(f"\n{symbol}-USD:")
            print(f"   Entry: ${entry_price:.2f} | Current: ${current_price:.2f} | Change: {pnl_pct:+.2f}%")
            print(f"   Position: ${entry_value:.2f} → ${current_value:.2f} | P&L: ${pnl:+.2f}")
            print(f"   Stops: SL=${stop_loss:.2f} | TP=${take_profit:.2f}")
            print(f"   Status: {status}")
            
        except Exception as e:
            print(f"\n{symbol}-USD:")
            print(f"   ❌ Error getting price: {e}")
    
    # Summary
    print("\n\n3️⃣ PORTFOLIO SUMMARY")
    print("-" * 80)
    total_pnl = total_current_value - total_entry_value
    total_pnl_pct = (total_pnl / total_entry_value) * 100 if total_entry_value > 0 else 0
    
    print(f"Entry value: ${total_entry_value:.2f}")
    print(f"Current value: ${total_current_value:.2f}")
    print(f"P&L: ${total_pnl:+.2f} ({total_pnl_pct:+.2f}%)")
    
    if total_pnl > 0:
        print(f"\n✅ PORTFOLIO IS WINNING - Should be locking in gains")
    else:
        print(f"\n📉 PORTFOLIO IS LOSING - Stops should be protecting downside")
    
    # Critical issues
    print("\n\n4️⃣ CRITICAL FINDINGS")
    print("-" * 80)
    
    if positions_to_close:
        print(f"⚠️ POSITIONS THAT SHOULD BE CLOSED ({len(positions_to_close)}):")
        for symbol, reason, price, pnl_pct in positions_to_close:
            print(f"   • {symbol} ({reason}): Current ${price:.2f}, P&L {pnl_pct:+.2f}%")
        print(f"\n❌ PROBLEM: These positions should have been closed but weren't!")
        print(f"   → This means the exit conditions are being triggered but orders not executing")
        print(f"   → OR the bot isn't checking positions frequently enough")
        print(f"   → OR there's an API error preventing the sells")
    else:
        print("✅ No positions at stop loss or take profit yet")
        print("   → Positions are still within their management zones")
        print("   → Need to wait for price movement OR adjust strategy entry points")
    
    print("\n" + "="*80 + "\n")

if __name__ == '__main__':
    main()
