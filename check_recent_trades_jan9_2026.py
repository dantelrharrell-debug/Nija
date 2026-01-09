#!/usr/bin/env python3
"""
Check Recent Trade Activity - January 9, 2026
Answers: Has NIJA made any trades for me and/or User #1?

Analyzes:
- trade_journal.jsonl for all historical trades
- data/trade_history.json for completed trades
- data/open_positions.json for current positions
- Checks if any trades occurred after bot startup (2026-01-09 11:39:14)
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def parse_timestamp(ts_string):
    """Parse various timestamp formats"""
    try:
        # Try ISO format with timezone
        if 'Z' in ts_string:
            return datetime.fromisoformat(ts_string.replace('Z', '+00:00'))
        elif '+' in ts_string or ts_string.endswith('00:00'):
            return datetime.fromisoformat(ts_string)
        else:
            # Assume UTC if no timezone
            return datetime.fromisoformat(ts_string).replace(tzinfo=timezone.utc)
    except Exception as e:
        print(f"Warning: Could not parse timestamp '{ts_string}': {e}")
        return None


def load_trade_journal():
    """Load all trades from trade_journal.jsonl"""
    journal_path = Path("trade_journal.jsonl")
    trades = []
    
    if not journal_path.exists():
        return trades
    
    with open(journal_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                trade = json.loads(line)
                trades.append(trade)
            except json.JSONDecodeError as e:
                print(f"Warning: Invalid JSON on line {line_num}: {e}")
    
    return trades


def load_trade_history():
    """Load completed trades from data/trade_history.json"""
    history_path = Path("data/trade_history.json")
    
    if not history_path.exists():
        return []
    
    try:
        with open(history_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load trade history: {e}")
        return []


def load_open_positions():
    """Load current open positions from data/open_positions.json"""
    positions_path = Path("data/open_positions.json")
    
    if not positions_path.exists():
        return {}
    
    try:
        with open(positions_path, 'r') as f:
            data = json.load(f)
            return data.get('positions', {})
    except Exception as e:
        print(f"Warning: Could not load open positions: {e}")
        return {}


def main():
    print("=" * 80)
    print("NIJA TRADING ACTIVITY REPORT - January 9, 2026")
    print("=" * 80)
    print()
    
    # Bot startup time from user's logs
    bot_startup = datetime(2026, 1, 9, 11, 39, 14, tzinfo=timezone.utc)
    print(f"📅 Bot Startup Time: {bot_startup.isoformat()}")
    print(f"🕐 Current Time: {datetime.now(timezone.utc).isoformat()}")
    print()
    
    # Load all data sources
    print("Loading trade data...")
    journal_trades = load_trade_journal()
    trade_history = load_trade_history()
    open_positions = load_open_positions()
    print()
    
    # Analyze trade journal
    print("=" * 80)
    print("TRADE JOURNAL ANALYSIS (trade_journal.jsonl)")
    print("=" * 80)
    print(f"Total trades in journal: {len(journal_trades)}")
    
    if journal_trades:
        # Find most recent trade
        most_recent = None
        most_recent_time = None
        
        for trade in journal_trades:
            ts = parse_timestamp(trade.get('timestamp', ''))
            if ts and (most_recent_time is None or ts > most_recent_time):
                most_recent_time = ts
                most_recent = trade
        
        if most_recent:
            print(f"\n📊 Most Recent Trade:")
            print(f"   Time: {most_recent_time.isoformat()}")
            print(f"   Symbol: {most_recent.get('symbol', 'N/A')}")
            print(f"   Side: {most_recent.get('side', 'N/A')}")
            print(f"   Price: ${most_recent.get('price', 'N/A')}")
            print(f"   Size: ${most_recent.get('size_usd', 'N/A')}")
            
            # Check if this was after bot startup
            if most_recent_time > bot_startup:
                print(f"   ✅ This trade was AFTER bot startup!")
            else:
                days_ago = (bot_startup - most_recent_time).days
                print(f"   ❌ This trade was {days_ago} days BEFORE bot startup")
        
        # Count trades by date
        trades_by_date = {}
        for trade in journal_trades:
            ts = parse_timestamp(trade.get('timestamp', ''))
            if ts:
                date_key = ts.date().isoformat()
                trades_by_date[date_key] = trades_by_date.get(date_key, 0) + 1
        
        print(f"\n📈 Trades by Date:")
        for date in sorted(trades_by_date.keys(), reverse=True)[:10]:
            print(f"   {date}: {trades_by_date[date]} trades")
    else:
        print("   ❌ No trades in journal")
    
    # Analyze trade history
    print()
    print("=" * 80)
    print("COMPLETED TRADES (data/trade_history.json)")
    print("=" * 80)
    print(f"Total completed trades: {len(trade_history)}")
    
    if trade_history:
        for i, trade in enumerate(trade_history[:5], 1):
            print(f"\n{i}. {trade.get('symbol', 'N/A')}")
            print(f"   Entry: ${trade.get('entry_price', 'N/A')} @ {trade.get('entry_time', 'N/A')}")
            print(f"   Exit: ${trade.get('exit_price', 'N/A')} @ {trade.get('exit_time', 'N/A')}")
            print(f"   P&L: ${trade.get('net_profit', 'N/A')} ({trade.get('profit_pct', 'N/A')}%)")
            print(f"   Exit Reason: {trade.get('exit_reason', 'N/A')}")
    else:
        print("   ❌ No completed trades")
    
    # Analyze open positions
    print()
    print("=" * 80)
    print("CURRENT OPEN POSITIONS (data/open_positions.json)")
    print("=" * 80)
    print(f"Total open positions: {len(open_positions)}")
    
    if open_positions:
        total_value = 0
        for symbol, pos in open_positions.items():
            size_usd = pos.get('size_usd', 0)
            total_value += size_usd
            entry_time = pos.get('entry_time', 'N/A')
            
            print(f"\n📍 {symbol}")
            print(f"   Entry Price: ${pos.get('entry_price', 'N/A')}")
            print(f"   Current Price: ${pos.get('current_price', 'N/A')}")
            print(f"   Size: ${size_usd}")
            print(f"   Quantity: {pos.get('crypto_quantity', 'N/A')}")
            print(f"   Entry Time: {entry_time}")
            print(f"   Stop Loss: ${pos.get('stop_loss', 'N/A')}")
            print(f"   Take Profit: ${pos.get('take_profit', 'N/A')}")
            
            # Check if synced from Coinbase (not a new trade)
            if pos.get('synced_from_coinbase'):
                print(f"   📝 Note: {pos.get('note', 'N/A')}")
        
        print(f"\n💰 Total Position Value: ${total_value:.2f}")
    else:
        print("   ❌ No open positions")
    
    # Final Answer
    print()
    print("=" * 80)
    print("🎯 ANSWER TO YOUR QUESTION")
    print("=" * 80)
    print()
    
    # Check for trades since startup
    trades_since_startup = []
    for trade in journal_trades:
        ts = parse_timestamp(trade.get('timestamp', ''))
        if ts and ts > bot_startup:
            trades_since_startup.append(trade)
    
    print(f"Question: Has any trades been made for me and/or User #1?")
    print(f"Bot Started: {bot_startup.isoformat()}")
    print()
    
    if trades_since_startup:
        print(f"✅ YES - {len(trades_since_startup)} trade(s) made AFTER bot startup!")
        print()
        for i, trade in enumerate(trades_since_startup, 1):
            ts = parse_timestamp(trade.get('timestamp', ''))
            print(f"{i}. {trade.get('symbol', 'N/A')} {trade.get('side', 'N/A')}")
            print(f"   Time: {ts.isoformat()}")
            print(f"   Price: ${trade.get('price', 'N/A')}")
            print(f"   Size: ${trade.get('size_usd', 'N/A')}")
    else:
        print(f"❌ NO - No trades made AFTER bot startup")
        print()
        
        if journal_trades:
            most_recent = None
            most_recent_time = None
            for trade in journal_trades:
                ts = parse_timestamp(trade.get('timestamp', ''))
                if ts and (most_recent_time is None or ts > most_recent_time):
                    most_recent_time = ts
                    most_recent = trade
            
            if most_recent_time:
                days_ago = (bot_startup - most_recent_time).days
                hours_ago = (bot_startup - most_recent_time).total_seconds() / 3600
                
                print(f"📊 Most Recent Trade Was:")
                print(f"   Date: {most_recent_time.isoformat()}")
                print(f"   Age: {days_ago} days ago ({hours_ago:.1f} hours)")
                print(f"   Symbol: {most_recent.get('symbol', 'N/A')}")
                print(f"   Side: {most_recent.get('side', 'N/A')}")
        else:
            print(f"📊 No trades found in trade journal at all")
    
    print()
    
    # Current status
    if open_positions:
        print(f"📍 CURRENT STATUS:")
        print(f"   Open Positions: {len(open_positions)}")
        print(f"   Total Value: ${sum(p.get('size_usd', 0) for p in open_positions.values()):.2f}")
        
        synced_count = sum(1 for p in open_positions.values() if p.get('synced_from_coinbase'))
        if synced_count > 0:
            print(f"   ⚠️  {synced_count} position(s) were synced from existing Coinbase holdings")
            print(f"       (These were NOT new trades by NIJA)")
    else:
        print(f"📍 CURRENT STATUS: No open positions")
    
    print()
    
    # User #1 status
    print(f"👤 USER #1 STATUS:")
    print(f"   From logs and documentation:")
    print(f"   - User #1 (Daivon Frazier) is configured but NOT ACTIVE")
    print(f"   - Bot is trading on Coinbase only (shared account)")
    print(f"   - Kraken is NOT connected")
    print(f"   - Multi-user system NOT initialized")
    print(f"   - All trades use the default Coinbase account")
    
    print()
    print("=" * 80)
    print("For more details, see: TRADING_STATUS_SUMMARY_JAN9_2026.md")
    print("=" * 80)


if __name__ == "__main__":
    main()
