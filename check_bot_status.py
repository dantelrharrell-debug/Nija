#!/usr/bin/env python3
"""
NIJA Bot Status Check - Verifies if trading is active
"""

import os
import sys
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def check_trade_journal():
    """Check if recent trades exist"""
    journal_path = 'trade_journal.jsonl'
    
    if not os.path.exists(journal_path):
        return None, "No trade journal found"
    
    try:
        with open(journal_path, 'r') as f:
            lines = f.readlines()
        
        if not lines:
            return None, "Trade journal is empty"
        
        # Get last trade
        last_line = lines[-1].strip()
        last_trade = json.loads(last_line)
        
        # Parse timestamp
        trade_time = datetime.fromisoformat(last_trade['timestamp'])
        now = datetime.now()
        time_ago = now - trade_time
        
        return {
            'timestamp': last_trade['timestamp'],
            'symbol': last_trade['symbol'],
            'side': last_trade['side'],
            'price': last_trade['price'],
            'age_minutes': int(time_ago.total_seconds() / 60)
        }, None
    except Exception as e:
        return None, str(e)

def main():
    print("=" * 70)
    print("NIJA BOT STATUS CHECK")
    print("=" * 70)
    print()
    
    # Check trade journal
    print("📊 CHECKING TRADE JOURNAL...")
    last_trade, error = check_trade_journal()
    
    if error:
        print(f"   ❌ {error}")
    elif last_trade:
        print(f"   ✅ Last trade: {last_trade['timestamp']}")
        print(f"      Symbol: {last_trade['symbol']}")
        print(f"      Side: {last_trade['side']}")
        print(f"      Price: {last_trade['price']:.2f}")
        print(f"      Time ago: {last_trade['age_minutes']} minutes")
        
        if last_trade['age_minutes'] < 5:
            print()
            print("   🟢 BOT IS ACTIVELY TRADING")
            status = "TRADING"
        elif last_trade['age_minutes'] < 60:
            print()
            print("   🟡 BOT WAS TRADING RECENTLY (< 1 hour)")
            status = "ACTIVE (recent)"
        else:
            print()
            print(f"   🔴 BOT NOT ACTIVE ({last_trade['age_minutes']} minutes since last trade)")
            status = "INACTIVE"
    
    print()
    print("=" * 70)
    
    # Check balance
    print()
    print("💰 CHECKING BALANCE DETECTION...")
    try:
        from broker_manager import CoinbaseBroker
        
        broker = CoinbaseBroker()
        if broker.connect():
            balance = broker.get_account_balance()
            trading_balance = balance.get('trading_balance', 0)
            
            print(f"   ✅ Connected to Coinbase")
            print(f"   💵 Trading Balance: ${trading_balance:,.2f}")
            
            if trading_balance > 50:
                print(f"      Status: ✅ SUFFICIENT (can trade)")
            elif trading_balance > 0:
                print(f"      Status: ⚠️  LOW (may limit trades)")
            else:
                print(f"      Status: ❌ ZERO (no trading)")
        else:
            print(f"   ❌ Failed to connect to Coinbase")
            print(f"      Check: COINBASE_API_KEY and COINBASE_API_SECRET")
    except Exception as e:
        print(f"   ❌ Balance check failed: {e}")
    
    print()
    print("=" * 70)
    print()
    print("📝 SUMMARY:")
    print()
    
    if last_trade and last_trade['age_minutes'] < 5:
        print("   ✅ Bot is running and trading actively")
        print("   ✅ No action needed")
    elif last_trade and last_trade['age_minutes'] < 60:
        print("   ⚠️  Bot was active < 1 hour ago")
        print("   Action: Monitor logs or restart if stuck")
        print("      ./restart.sh")
    else:
        print("   ❌ Bot is not trading (may be stopped)")
        print("   Action: Restart the bot")
        print("      ./restart.sh")
    
    print()
    print("=" * 70)

if __name__ == "__main__":
    main()
