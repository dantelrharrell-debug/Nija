#!/usr/bin/env python3
"""
NIJA Active Trading Status per Brokerage
=========================================

This script checks whether NIJA is actively trading on each connected brokerage.

For each broker, it shows:
1. Connection status (Connected/Not Connected)
2. Open positions (actively trading if any exist)
3. Recent trading activity from trade journal
4. Trading readiness status

Usage:
    python3 check_active_trading_per_broker.py
"""

import os
import sys
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def print_header(title):
    """Print a formatted header"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_section(title):
    """Print a formatted section title"""
    print("\n" + "-" * 80)
    print(f"  {title}")
    print("-" * 80)

def get_recent_trades_from_journal(hours=24):
    """
    Load recent trades from trade_journal.jsonl
    
    Returns:
        dict: Trades grouped by symbol, with timestamps
    """
    journal_file = "trade_journal.jsonl"
    
    if not os.path.exists(journal_file):
        return {}
    
    trades_by_symbol = {}
    cutoff_time = datetime.now() - timedelta(hours=hours)
    
    try:
        with open(journal_file, 'r') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    trade = json.loads(line)
                    timestamp = datetime.fromisoformat(trade.get('timestamp', ''))
                    
                    if timestamp < cutoff_time:
                        continue
                    
                    symbol = trade.get('symbol', 'UNKNOWN')
                    if symbol not in trades_by_symbol:
                        trades_by_symbol[symbol] = []
                    
                    trades_by_symbol[symbol].append({
                        'side': trade.get('side'),
                        'price': trade.get('price', 0),
                        'size_usd': trade.get('size_usd', 0),
                        'timestamp': timestamp
                    })
                except Exception as e:
                    continue
    except Exception as e:
        print(f"⚠️ Could not read trade journal: {e}")
    
    return trades_by_symbol

def check_broker_trading_status(broker_name, broker_class):
    """
    Check if a broker is actively trading
    
    Returns:
        dict with status info
    """
    status = {
        'connected': False,
        'balance': 0.0,
        'positions': [],
        'position_count': 0,
        'is_trading': False,
        'error': None
    }
    
    try:
        broker = broker_class()
        
        # Try to connect
        if not broker.connect():
            status['error'] = "Connection failed"
            return status
        
        status['connected'] = True
        
        # Get balance
        try:
            balance = broker.get_account_balance()
            status['balance'] = float(balance) if balance else 0.0
        except Exception as e:
            status['error'] = f"Balance check failed: {str(e)[:50]}"
        
        # Get positions
        try:
            positions = broker.get_positions()
            status['positions'] = positions or []
            status['position_count'] = len(status['positions'])
            
            # If there are open positions, the broker is actively trading
            if status['position_count'] > 0:
                status['is_trading'] = True
        except Exception as e:
            status['error'] = f"Position check failed: {str(e)[:50]}"
    
    except Exception as e:
        status['error'] = str(e)[:100]
    
    return status

def main():
    """Main function to check active trading status per broker"""
    print_header("NIJA Active Trading Status Report")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Import broker classes
    try:
        from broker_manager import (
            CoinbaseBroker, KrakenBroker, OKXBroker, 
            BinanceBroker, AlpacaBroker
        )
    except ImportError as e:
        print(f"\n❌ Error importing broker classes: {e}")
        sys.exit(1)
    
    # Define broker configurations
    brokers = [
        {
            'name': 'Coinbase Advanced Trade',
            'class': CoinbaseBroker,
            'icon': '🟦',
            'primary': True,
            'type': 'Crypto'
        },
        {
            'name': 'Kraken Pro',
            'class': KrakenBroker,
            'icon': '🟪',
            'primary': False,
            'type': 'Crypto'
        },
        {
            'name': 'OKX',
            'class': OKXBroker,
            'icon': '⬛',
            'primary': False,
            'type': 'Crypto'
        },
        {
            'name': 'Binance',
            'class': BinanceBroker,
            'icon': '🟨',
            'primary': False,
            'type': 'Crypto'
        },
        {
            'name': 'Alpaca',
            'class': AlpacaBroker,
            'icon': '🟩',
            'primary': False,
            'type': 'Stocks'
        }
    ]
    
    # Get recent trades from journal
    print_section("Loading Recent Trading Activity (Last 24h)")
    recent_trades = get_recent_trades_from_journal(hours=24)
    
    if recent_trades:
        total_trades = sum(len(trades) for trades in recent_trades.values())
        print(f"\n✅ Found {total_trades} trades across {len(recent_trades)} symbols in the last 24 hours")
        
        # Show top 5 most actively traded symbols
        sorted_symbols = sorted(recent_trades.items(), key=lambda x: len(x[1]), reverse=True)
        print("\n📊 Most Active Symbols:")
        for symbol, trades in sorted_symbols[:5]:
            buys = sum(1 for t in trades if t['side'] == 'BUY')
            sells = sum(1 for t in trades if t['side'] == 'SELL')
            print(f"   {symbol}: {len(trades)} trades (🟢 {buys} buys, 🔴 {sells} sells)")
    else:
        print("\nℹ️ No recent trades found in journal")
    
    # Check each broker
    print_section("Checking Active Trading Status per Broker")
    
    broker_statuses = []
    actively_trading = []
    connected_but_idle = []
    not_connected = []
    total_positions = 0
    total_balance = 0.0
    
    for broker_config in brokers:
        name = broker_config['name']
        icon = broker_config['icon']
        broker_class = broker_config['class']
        primary = broker_config['primary']
        asset_type = broker_config['type']
        
        print(f"\n{icon} {name} ({asset_type})" + (" [PRIMARY]" if primary else ""))
        print(f"   🔄 Checking status...")
        
        status = check_broker_trading_status(name, broker_class)
        status['name'] = name
        status['icon'] = icon
        status['type'] = asset_type
        status['primary'] = primary
        broker_statuses.append(status)
        
        if not status['connected']:
            print(f"   ❌ Not Connected")
            if status['error']:
                print(f"   Error: {status['error']}")
            not_connected.append(status)
            continue
        
        print(f"   ✅ Connected")
        
        # Show balance
        if status['balance'] > 0:
            print(f"   💰 Balance: ${status['balance']:,.2f}")
            total_balance += status['balance']
        else:
            print(f"   💰 Balance: $0.00")
        
        # Show positions
        if status['position_count'] > 0:
            print(f"   📊 Open Positions: {status['position_count']}")
            total_positions += status['position_count']
            
            # Show position details
            for pos in status['positions'][:5]:  # Show max 5 positions
                symbol = pos.get('symbol', 'UNKNOWN')
                quantity = pos.get('quantity', 0)
                currency = pos.get('currency', '')
                print(f"      • {symbol}: {quantity:.8f} {currency}")
            
            if status['position_count'] > 5:
                print(f"      ... and {status['position_count'] - 5} more")
            
            print(f"   🟢 STATUS: ACTIVELY TRADING")
            actively_trading.append(status)
        else:
            print(f"   📊 Open Positions: 0")
            print(f"   ⚪ STATUS: Connected but no open positions")
            connected_but_idle.append(status)
    
    # Print summary
    print_header("ACTIVE TRADING SUMMARY")
    
    print(f"\n📊 Overall Status:")
    print(f"   • Total Brokers Checked: {len(brokers)}")
    print(f"   • Connected Brokers: {len(actively_trading) + len(connected_but_idle)}")
    print(f"   • Actively Trading: {len(actively_trading)}")
    print(f"   • Connected but Idle: {len(connected_but_idle)}")
    print(f"   • Not Connected: {len(not_connected)}")
    
    if actively_trading:
        print(f"\n✅ BROKERS ACTIVELY TRADING ({len(actively_trading)}):")
        for broker in actively_trading:
            primary_tag = " [PRIMARY]" if broker.get('primary') else ""
            print(f"   {broker['icon']} {broker['name']}{primary_tag}")
            print(f"      💰 Balance: ${broker['balance']:,.2f}")
            print(f"      📊 Open Positions: {broker['position_count']}")
    else:
        print(f"\n⚠️ NO BROKERS ACTIVELY TRADING")
        print("   (No open positions detected on any connected broker)")
    
    if connected_but_idle:
        print(f"\n⚪ CONNECTED BUT IDLE ({len(connected_but_idle)}):")
        for broker in connected_but_idle:
            print(f"   {broker['icon']} {broker['name']}")
            print(f"      💰 Balance: ${broker['balance']:,.2f}")
            print(f"      📊 Open Positions: 0")
            print(f"      ℹ️ Ready to trade but no positions currently open")
    
    if not_connected:
        print(f"\n❌ NOT CONNECTED ({len(not_connected)}):")
        for broker in not_connected:
            print(f"   {broker['icon']} {broker['name']}")
    
    # Trading activity summary
    print_section("Trading Activity Analysis")
    
    if total_positions > 0:
        print(f"\n📈 Total Open Positions Across All Brokers: {total_positions}")
        print(f"💰 Total Balance Across All Brokers: ${total_balance:,.2f}")
        
        if actively_trading:
            print(f"\n✅ NIJA IS ACTIVELY TRADING")
            print(f"\n   Primary Broker: {next((b['name'] for b in actively_trading if b.get('primary')), actively_trading[0]['name'])}")
            print(f"   Active Exchanges: {len(actively_trading)}")
            print(f"   Combined Open Positions: {total_positions}")
            
            if recent_trades:
                print(f"   Recent Activity (24h): {sum(len(t) for t in recent_trades.values())} trades")
    else:
        print(f"\n⚠️ NO ACTIVE POSITIONS")
        print("\nNIJA is connected but not currently holding any positions.")
        print("This could mean:")
        print("  • Bot is waiting for entry signals")
        print("  • All positions were recently closed")
        print("  • Bot just started and hasn't entered any trades yet")
        
        if recent_trades:
            print(f"\nℹ️ Recent activity detected ({sum(len(t) for t in recent_trades.values())} trades in last 24h)")
            print("   The bot has been trading recently but all positions are now closed")
    
    # Recommendations
    if not actively_trading and not connected_but_idle:
        print_section("Recommendations")
        print("\n📝 To enable trading:")
        print("   1. Configure broker credentials in .env file")
        print("   2. Ensure minimum balance requirements are met")
        print("   3. Start the bot: ./start.sh")
        print("   4. Monitor logs for trading activity")
    
    print("\n" + "=" * 80 + "\n")
    
    # Exit code: 0 if any broker is actively trading, 1 if no active trading
    if actively_trading:
        sys.exit(0)
    else:
        sys.exit(1)

if __name__ == "__main__":
    main()
