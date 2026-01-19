#!/usr/bin/env python3
"""
NIJA System Status Verification Script
Checks for losing trades and Kraken trading readiness
"""

import os
import json
import sys
from datetime import datetime
from pathlib import Path

def check_environment_variables():
    """Check if required environment variables are set"""
    print("\n" + "="*70)
    print("🔍 CHECKING ENVIRONMENT VARIABLES")
    print("="*70)
    
    # Coinbase credentials
    coinbase_key = os.getenv('COINBASE_API_KEY') or os.getenv('COINBASE_MASTER_API_KEY')
    coinbase_secret = os.getenv('COINBASE_API_SECRET') or os.getenv('COINBASE_MASTER_API_SECRET')
    
    print("\n📊 COINBASE (Primary Exchange)")
    print(f"   API Key: {'✅ SET' if coinbase_key else '❌ NOT SET'}")
    print(f"   API Secret: {'✅ SET' if coinbase_secret else '❌ NOT SET'}")
    
    # Kraken credentials
    kraken_master_key = os.getenv('KRAKEN_MASTER_API_KEY')
    kraken_master_secret = os.getenv('KRAKEN_MASTER_API_SECRET')
    
    print("\n🦑 KRAKEN (Master Account)")
    print(f"   API Key: {'✅ SET' if kraken_master_key else '❌ NOT SET'}")
    print(f"   API Secret: {'✅ SET' if kraken_master_secret else '❌ NOT SET'}")
    
    # Kraken users
    users = ['daivon_frazier', 'tania']
    kraken_users_configured = 0
    
    for user in users:
        key = os.getenv(f'KRAKEN_USER_{user}_API_KEY')
        secret = os.getenv(f'KRAKEN_USER_{user}_API_SECRET')
        has_creds = key and secret
        if has_creds:
            kraken_users_configured += 1
        print(f"\n🦑 KRAKEN User: {user}")
        print(f"   API Key: {'✅ SET' if key else '❌ NOT SET'}")
        print(f"   API Secret: {'✅ SET' if secret else '❌ NOT SET'}")
    
    return {
        'coinbase': bool(coinbase_key and coinbase_secret),
        'kraken_master': bool(kraken_master_key and kraken_master_secret),
        'kraken_users': kraken_users_configured
    }

def check_open_positions():
    """Check for open positions that might be losing"""
    print("\n" + "="*70)
    print("📊 CHECKING OPEN POSITIONS")
    print("="*70)
    
    positions_file = Path('data/open_positions.json')
    
    if not positions_file.exists():
        print("\n   ℹ️  No positions file found - bot may be starting fresh")
        return {'count': 0, 'positions': []}
    
    try:
        # Read file content
        with open(positions_file, 'r') as f:
            content = f.read()
        
        # Try to parse JSON - file may be malformed
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            print(f"\n   ⚠️  Positions file is malformed: {e}")
            print(f"   📝 File size: {len(content)} bytes")
            # Try to find the last valid JSON by looking for closing brace
            last_brace = content.rfind('}')
            if last_brace > 0:
                try:
                    data = json.loads(content[:last_brace+1])
                    print(f"   ✅ Recovered partial data")
                except:
                    print(f"   ❌ Could not recover data")
                    return {'count': 0, 'positions': []}
            else:
                return {'count': 0, 'positions': []}
        
        positions = data.get('positions', {})
        timestamp = data.get('timestamp', 'unknown')
        
        print(f"\n   📅 Last Updated: {timestamp}")
        print(f"   📈 Total Positions: {len(positions)}")
        
        if len(positions) == 0:
            print("\n   ✅ No open positions - all capital available")
            return {'count': 0, 'positions': []}
        
        print("\n   Positions:")
        position_list = []
        for symbol, pos in positions.items():
            entry = pos.get('entry_price', 'N/A')
            current = pos.get('current_price', entry)  # Use entry if current not available
            size = pos.get('size_usd', 0)
            entry_time = pos.get('entry_time', 'unknown')
            
            # Calculate age if entry time available
            age_str = "unknown"
            if entry_time != 'unknown':
                try:
                    entry_dt = datetime.fromisoformat(entry_time.replace('Z', '+00:00'))
                    now = datetime.now(entry_dt.tzinfo) if entry_dt.tzinfo else datetime.now()
                    age_hours = (now - entry_dt).total_seconds() / 3600
                    age_str = f"{age_hours:.1f}h"
                except:
                    pass
            
            # Calculate P&L if both prices available
            pnl_str = "N/A"
            if entry != 'N/A' and current != 'N/A':
                try:
                    entry_float = float(entry)
                    current_float = float(current)
                    pnl_pct = ((current_float - entry_float) / entry_float) * 100
                    pnl_str = f"{pnl_pct:+.2f}%"
                except:
                    pass
            
            status = "⚠️ "
            if pnl_str != "N/A":
                if "+" in pnl_str:
                    status = "✅"
                elif "-" in pnl_str:
                    status = "❌"
            
            print(f"   {status} {symbol}:")
            print(f"      Entry: ${entry}, Current: ${current}")
            print(f"      Size: ${size:.2f}, P&L: {pnl_str}, Age: {age_str}")
            
            position_list.append({
                'symbol': symbol,
                'entry': entry,
                'current': current,
                'size': size,
                'pnl': pnl_str,
                'age': age_str
            })
        
        return {'count': len(positions), 'positions': position_list}
        
    except Exception as e:
        print(f"\n   ❌ Error reading positions file: {e}")
        return {'count': 0, 'positions': []}

def check_position_tracker():
    """Check position tracker for tracked positions"""
    print("\n" + "="*70)
    print("📋 CHECKING POSITION TRACKER")
    print("="*70)
    
    tracker_file = Path('positions.json')
    
    if not tracker_file.exists():
        print("\n   ℹ️  No position tracker file found")
        print("   ⚠️  Positions may not have entry prices tracked!")
        print("   💡 This could cause the auto-import masking issue")
        return {'tracked': 0}
    
    try:
        with open(tracker_file, 'r') as f:
            data = json.load(f)
        
        positions = data.get('positions', {})
        last_updated = data.get('last_updated', 'unknown')
        
        print(f"\n   📅 Last Updated: {last_updated}")
        print(f"   📈 Tracked Positions: {len(positions)}")
        
        if len(positions) > 0:
            print("\n   Tracked:")
            for symbol, pos in positions.items():
                entry = pos.get('entry_price', 'N/A')
                quantity = pos.get('quantity', 0)
                size = pos.get('size_usd', 0)
                first_entry = pos.get('first_entry_time', 'unknown')
                strategy = pos.get('strategy', 'unknown')
                
                print(f"   ✅ {symbol}:")
                print(f"      Entry: ${entry}, Qty: {quantity:.8f}")
                print(f"      Size: ${size:.2f}, Strategy: {strategy}")
                print(f"      First Entry: {first_entry}")
        
        return {'tracked': len(positions)}
        
    except Exception as e:
        print(f"\n   ❌ Error reading position tracker: {e}")
        return {'tracked': 0}

def check_trade_journal():
    """Check recent trading activity"""
    print("\n" + "="*70)
    print("📜 CHECKING TRADE JOURNAL")
    print("="*70)
    
    journal_file = Path('trade_journal.jsonl')
    
    if not journal_file.exists():
        print("\n   ℹ️  No trade journal found - no trades yet")
        return {'total': 0, 'last_trade': None}
    
    try:
        with open(journal_file, 'r') as f:
            lines = f.readlines()
        
        total_trades = len(lines)
        print(f"\n   📊 Total Trades: {total_trades}")
        
        if total_trades == 0:
            print("\n   ⚠️  No trades recorded - bot may be inactive")
            return {'total': 0, 'last_trade': None}
        
        # Count by exchange
        coinbase_trades = 0
        kraken_trades = 0
        
        for line in lines:
            try:
                trade = json.loads(line)
                symbol = trade.get('symbol', '')
                # Kraken trades might have different symbol format or exchange field
                # For now, assume all are Coinbase unless otherwise marked
                coinbase_trades += 1
            except:
                pass
        
        print(f"\n   📊 Coinbase Trades: {coinbase_trades}")
        print(f"   🦑 Kraken Trades: {kraken_trades}")
        
        # Get last trade
        try:
            last_trade = json.loads(lines[-1])
            timestamp = last_trade.get('timestamp', 'unknown')
            symbol = last_trade.get('symbol', 'unknown')
            side = last_trade.get('side', 'unknown')
            price = last_trade.get('price', 0)
            
            print(f"\n   ⏰ Last Trade:")
            print(f"      Time: {timestamp}")
            print(f"      {side} {symbol} @ ${price}")
            
            # Calculate days since last trade
            if timestamp != 'unknown':
                try:
                    trade_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    now = datetime.now(trade_dt.tzinfo) if trade_dt.tzinfo else datetime.now()
                    days_ago = (now - trade_dt).total_seconds() / 86400
                    print(f"      ({days_ago:.1f} days ago)")
                    
                    if days_ago > 7:
                        print(f"\n   ⚠️  WARNING: No trades in {days_ago:.1f} days!")
                        print(f"   💡 Bot may be inactive or misconfigured")
                except:
                    pass
            
            return {'total': total_trades, 'last_trade': timestamp, 'kraken': kraken_trades}
            
        except:
            return {'total': total_trades, 'last_trade': None, 'kraken': kraken_trades}
        
    except Exception as e:
        print(f"\n   ❌ Error reading trade journal: {e}")
        return {'total': 0, 'last_trade': None}

def print_summary(creds, positions, tracker, trades):
    """Print summary and recommendations"""
    print("\n" + "="*70)
    print("📋 SUMMARY & RECOMMENDATIONS")
    print("="*70)
    
    print("\n🔧 SYSTEM STATUS:")
    
    # Coinbase
    if creds['coinbase']:
        print("   ✅ Coinbase: CONFIGURED")
    else:
        print("   ❌ Coinbase: NOT CONFIGURED")
        print("      ACTION: Set COINBASE_API_KEY and COINBASE_API_SECRET")
    
    # Kraken
    if creds['kraken_master']:
        print("   ✅ Kraken Master: CONFIGURED")
    else:
        print("   ❌ Kraken Master: NOT CONFIGURED")
        print("      ACTION: Set KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET")
    
    if creds['kraken_users'] == 2:
        print("   ✅ Kraken Users: ALL CONFIGURED (2/2)")
    elif creds['kraken_users'] > 0:
        print(f"   ⚠️  Kraken Users: PARTIAL ({creds['kraken_users']}/2)")
        print("      ACTION: Configure remaining user accounts")
    else:
        print("   ❌ Kraken Users: NOT CONFIGURED (0/2)")
        print("      ACTION: Set Kraken API keys for daivon_frazier and tania")
    
    # Trading Activity
    print(f"\n📊 TRADING ACTIVITY:")
    if trades['total'] > 0:
        print(f"   Total Trades: {trades['total']}")
        print(f"   Kraken Trades: {trades.get('kraken', 0)}")
        if trades['last_trade']:
            print(f"   Last Trade: {trades['last_trade']}")
    else:
        print("   ⚠️  No trades recorded")
        print("      Bot may be inactive or just started")
    
    # Open Positions
    print(f"\n💼 OPEN POSITIONS:")
    if positions['count'] > 0:
        print(f"   Total: {positions['count']}")
        losing_positions = [p for p in positions['positions'] if '-' in str(p.get('pnl', ''))]
        if losing_positions:
            print(f"   ⚠️  Losing: {len(losing_positions)}")
            print("      These should exit automatically with zombie detection fix")
    else:
        print("   ✅ No open positions")
    
    # Position Tracking
    print(f"\n📋 POSITION TRACKING:")
    if tracker['tracked'] == positions['count']:
        print(f"   ✅ All {positions['count']} positions tracked")
    elif tracker['tracked'] < positions['count']:
        missing = positions['count'] - tracker['tracked']
        print(f"   ⚠️  {missing} positions NOT tracked (may be auto-imported)")
        print("      Zombie detection will catch these after 1 hour at 0% P&L")
    
    # Action Items
    print(f"\n📝 ACTION ITEMS:")
    
    action_count = 0
    
    if not creds['kraken_master']:
        action_count += 1
        print(f"   {action_count}. Set up Kraken master account API keys")
        print("      See: KRAKEN_NOT_TRADING_SOLUTION_JAN_19_2026.md")
    
    if creds['kraken_users'] < 2:
        action_count += 1
        print(f"   {action_count}. Set up Kraken user account API keys")
        print("      See: KRAKEN_NOT_TRADING_SOLUTION_JAN_19_2026.md")
    
    if trades['total'] == 0 or (trades.get('last_trade') and '2025-12' in trades['last_trade']):
        action_count += 1
        print(f"   {action_count}. Verify bot is running (no recent trades)")
        print("      Check Railway/Render deployment status")
    
    if positions['count'] > 0 and tracker['tracked'] < positions['count']:
        action_count += 1
        print(f"   {action_count}. Monitor for zombie position auto-exits")
        print("      Check logs for '🧟 ZOMBIE POSITION DETECTED' messages")
    
    if action_count == 0:
        print("   ✅ No immediate action needed!")
        print("   💡 Monitor logs for zombie detections and Kraken trades")
    
    print("\n" + "="*70)
    print("✅ VERIFICATION COMPLETE")
    print("="*70 + "\n")

def main():
    """Main verification routine"""
    print("\n" + "="*70)
    print("🤖 NIJA SYSTEM STATUS VERIFICATION")
    print("="*70)
    print("Checking for losing trades and Kraken trading readiness...")
    
    # Load environment from .env if available
    try:
        from dotenv import load_dotenv
        load_dotenv()
        print("✅ Environment variables loaded from .env")
    except:
        print("ℹ️  Using system environment variables")
    
    # Run checks
    creds = check_environment_variables()
    positions = check_open_positions()
    tracker = check_position_tracker()
    trades = check_trade_journal()
    
    # Print summary
    print_summary(creds, positions, tracker, trades)

if __name__ == "__main__":
    main()
