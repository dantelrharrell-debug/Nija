#!/usr/bin/env python3
"""
NIJA Trading Status and Profit Report
======================================

Checks if NIJA is trading for master and user accounts, and calculates profits.

This script:
1. Checks if master account is connected and trading
2. Checks if user accounts are connected and trading
3. Calculates total profits for each account
4. Reports account balances
5. Shows recent trade activity

Author: NIJA Trading Systems
Date: January 2026
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)


def load_env_from_file(path: str = ".env") -> None:
    """Load environment variables from .env file."""
    if not os.path.isfile(path):
        return
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                
                if key not in os.environ:
                    os.environ[key] = value
    except Exception as e:
        logger.warning(f"Could not load .env file: {e}")


def check_master_credentials() -> dict:
    """Check which brokers have master credentials configured."""
    credentials = {
        'coinbase': False,
        'kraken': False,
        'alpaca': False,
        'okx': False,
        'binance': False
    }
    
    # Coinbase
    if os.getenv('COINBASE_API_KEY') and os.getenv('COINBASE_API_SECRET'):
        credentials['coinbase'] = True
    
    # Kraken
    if os.getenv('KRAKEN_MASTER_API_KEY') and os.getenv('KRAKEN_MASTER_API_SECRET'):
        credentials['kraken'] = True
    
    # Alpaca
    if os.getenv('ALPACA_API_KEY') and os.getenv('ALPACA_API_SECRET'):
        credentials['alpaca'] = True
    
    # OKX
    if os.getenv('OKX_API_KEY') and os.getenv('OKX_API_SECRET'):
        credentials['okx'] = True
    
    # Binance
    if os.getenv('BINANCE_API_KEY') and os.getenv('BINANCE_API_SECRET'):
        credentials['binance'] = True
    
    return credentials


def check_user_credentials() -> dict:
    """Check which users have credentials configured."""
    users = {
        'daivon_frazier': {'kraken': False, 'alpaca': False},
        'tania_gilbert': {'kraken': False, 'alpaca': False}
    }
    
    # Daivon Frazier - Kraken
    if os.getenv('KRAKEN_USER_DAIVON_API_KEY') and os.getenv('KRAKEN_USER_DAIVON_API_SECRET'):
        users['daivon_frazier']['kraken'] = True
    
    # Tania Gilbert - Kraken
    if os.getenv('KRAKEN_USER_TANIA_API_KEY') and os.getenv('KRAKEN_USER_TANIA_API_SECRET'):
        users['tania_gilbert']['kraken'] = True
    
    # Daivon Frazier - Alpaca
    if os.getenv('ALPACA_USER_DAIVON_API_KEY') and os.getenv('ALPACA_USER_DAIVON_API_SECRET'):
        users['daivon_frazier']['alpaca'] = True
    
    # Tania Gilbert - Alpaca
    if os.getenv('ALPACA_USER_TANIA_API_KEY') and os.getenv('ALPACA_USER_TANIA_API_SECRET'):
        users['tania_gilbert']['alpaca'] = True
    
    return users


def get_coinbase_balance() -> float:
    """Get Coinbase balance for master account."""
    try:
        from coinbase.rest import RESTClient
        
        api_key = os.getenv('COINBASE_API_KEY')
        api_secret = os.getenv('COINBASE_API_SECRET')
        
        if not api_key or not api_secret:
            return None
        
        # Normalize PEM key if needed
        if '\\n' in api_secret:
            api_secret = api_secret.replace('\\n', '\n')
        
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        resp = client.get_accounts()
        accounts = getattr(resp, "accounts", []) or []
        
        total = 0.0
        for account in accounts:
            currency = getattr(account, "currency", "")
            if currency in ["USD", "USDC"]:
                balance_obj = getattr(account, "available_balance", None)
                value = float(getattr(balance_obj, "value", 0) or 0)
                total += value
        
        return total
    except Exception as e:
        logger.error(f"Error getting Coinbase balance: {e}")
        return None


def load_trade_history() -> dict:
    """Load trade history from data files."""
    history = {
        'total_trades': 0,
        'profitable_trades': 0,
        'losing_trades': 0,
        'total_profit': 0.0,
        'recent_trades': []
    }
    
    # Load from data/trade_history.json
    trade_history_file = Path("data/trade_history.json")
    if trade_history_file.exists():
        try:
            with open(trade_history_file, 'r') as f:
                trades = json.load(f)
                if isinstance(trades, list):
                    history['total_trades'] = len(trades)
                    for trade in trades:
                        if 'net_profit' in trade:
                            profit = trade['net_profit']
                            history['total_profit'] += profit
                            if profit > 0:
                                history['profitable_trades'] += 1
                            else:
                                history['losing_trades'] += 1
                        history['recent_trades'].append(trade)
        except Exception as e:
            logger.warning(f"Error loading trade_history.json: {e}")
    
    # Load from trade_journal.jsonl
    trade_journal_file = Path("trade_journal.jsonl")
    if trade_journal_file.exists():
        try:
            journal_trades = []
            with open(trade_journal_file, 'r') as f:
                for line in f:
                    if line.strip():
                        trade = json.loads(line)
                        journal_trades.append(trade)
            
            # If we have more trades in journal than in history, use journal
            if len(journal_trades) > len(history['recent_trades']):
                history['recent_trades'] = journal_trades[-20:]  # Last 20 trades
        except Exception as e:
            logger.warning(f"Error loading trade_journal.jsonl: {e}")
    
    # Load daily profit history
    daily_profit_file = Path("data/daily_profit_history.json")
    if daily_profit_file.exists():
        try:
            with open(daily_profit_file, 'r') as f:
                daily_profits = json.load(f)
                if isinstance(daily_profits, dict):
                    # If we don't have total profit from trades, calculate from daily
                    if history['total_profit'] == 0.0:
                        history['total_profit'] = sum(daily_profits.values())
        except Exception as e:
            logger.warning(f"Error loading daily_profit_history.json: {e}")
    
    return history


def print_divider(char="=", length=80):
    """Print a divider line."""
    print(char * length)


def print_section_header(title: str):
    """Print a section header."""
    print()
    print_divider("=")
    print(f"  {title}")
    print_divider("=")


def print_status_icon(connected: bool) -> str:
    """Return status icon based on connection state."""
    return "✅" if connected else "❌"


def main():
    """Main function to check trading status and profits."""
    print_divider("=")
    print("  🤖 NIJA TRADING STATUS AND PROFIT REPORT")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print_divider("=")
    
    # Load environment variables
    load_env_from_file()
    
    # Check master credentials
    print_section_header("MASTER ACCOUNT (NIJA System)")
    master_creds = check_master_credentials()
    
    print("\n📊 Broker Connections:")
    master_connected_count = 0
    master_trading_brokers = []
    
    for broker, has_creds in master_creds.items():
        status = print_status_icon(has_creds)
        status_text = "CONFIGURED" if has_creds else "NOT CONFIGURED"
        print(f"   {status} {broker.upper()}: {status_text}")
        if has_creds:
            master_connected_count += 1
            master_trading_brokers.append(broker.upper())
    
    print(f"\n📈 Total Configured Brokers: {master_connected_count}/5")
    
    # Get Coinbase balance if available
    if master_creds['coinbase']:
        print("\n💰 Master Account Balance (Coinbase):")
        balance = get_coinbase_balance()
        if balance is not None:
            print(f"   Total: ${balance:,.2f} USD")
        else:
            print("   ⚠️  Could not retrieve balance")
    
    # Check user accounts
    print_section_header("USER ACCOUNTS")
    user_creds = check_user_credentials()
    
    total_users_trading = 0
    
    for user_id, brokers in user_creds.items():
        user_name = user_id.replace('_', ' ').title()
        print(f"\n👤 {user_name}:")
        
        user_has_connection = False
        for broker, has_creds in brokers.items():
            status = print_status_icon(has_creds)
            status_text = "CONFIGURED" if has_creds else "NOT CONFIGURED"
            print(f"   {status} {broker.upper()}: {status_text}")
            if has_creds:
                user_has_connection = True
        
        if user_has_connection:
            total_users_trading += 1
            print(f"   Status: ✅ READY TO TRADE")
        else:
            print(f"   Status: ❌ NOT TRADING (No credentials configured)")
    
    # Load and display trade history
    print_section_header("TRADING ACTIVITY & PROFITS")
    
    trade_history = load_trade_history()
    
    print(f"\n📊 Trade Statistics:")
    print(f"   Total Trades: {trade_history['total_trades']}")
    print(f"   Profitable Trades: {trade_history['profitable_trades']}")
    print(f"   Losing Trades: {trade_history['losing_trades']}")
    
    if trade_history['total_trades'] > 0:
        win_rate = (trade_history['profitable_trades'] / trade_history['total_trades']) * 100
        print(f"   Win Rate: {win_rate:.1f}%")
    
    print(f"\n💵 Total Profit/Loss: ${trade_history['total_profit']:,.2f}")
    
    if trade_history['total_profit'] > 0:
        print(f"   Status: 🟢 PROFITABLE")
    elif trade_history['total_profit'] < 0:
        print(f"   Status: 🔴 IN LOSS")
    else:
        print(f"   Status: ⚪ BREAKEVEN")
    
    # Recent trades
    if trade_history['recent_trades']:
        print(f"\n📋 Recent Trades (Last 10):")
        recent = trade_history['recent_trades'][-10:]
        
        for i, trade in enumerate(recent, 1):
            symbol = trade.get('symbol', 'UNKNOWN')
            side = trade.get('side', 'N/A')
            
            # Check if this is a complete trade with P&L
            if 'net_profit' in trade:
                profit = trade['net_profit']
                profit_str = f"${profit:+.2f}"
                if profit > 0:
                    profit_icon = "🟢"
                elif profit < 0:
                    profit_icon = "🔴"
                else:
                    profit_icon = "⚪"
                
                timestamp = trade.get('timestamp', trade.get('exit_time', 'N/A'))
                print(f"   {i}. {profit_icon} {symbol} {side} - {profit_str} ({timestamp})")
            else:
                # Just entry/exit info
                price = trade.get('price', 0)
                size = trade.get('size_usd', 0)
                timestamp = trade.get('timestamp', 'N/A')
                print(f"   {i}. {symbol} {side} @ ${price:.2f} (${size:.2f}) - {timestamp}")
    
    # Summary
    print_section_header("SUMMARY")
    
    print("\n❓ Is NIJA trading for the master and the users?")
    print()
    
    # Master summary
    if master_connected_count > 0:
        print(f"✅ YES - Master account is configured to trade on {master_connected_count} broker(s):")
        for broker in master_trading_brokers:
            print(f"   • {broker}")
    else:
        print("❌ NO - Master account has no broker credentials configured")
    
    print()
    
    # Users summary
    if total_users_trading > 0:
        print(f"✅ YES - {total_users_trading} user(s) configured to trade:")
        for user_id, brokers in user_creds.items():
            user_has_connection = any(brokers.values())
            if user_has_connection:
                user_name = user_id.replace('_', ' ').title()
                user_brokers = [b.upper() for b, v in brokers.items() if v]
                print(f"   • {user_name}: {', '.join(user_brokers)}")
    else:
        print("❌ NO - No users have broker credentials configured")
    
    print()
    print("💰 How much has the master and both users profited so far?")
    print()
    
    # Note: Without live connection, we can only show combined historical profits
    print(f"📊 Combined Historical Profit (All Accounts): ${trade_history['total_profit']:,.2f}")
    print()
    print("⚠️  Note: Individual profit breakdown by account requires live broker connections.")
    print("   The profit shown above is from historical trade data and may include all accounts.")
    print()
    
    if master_creds['coinbase']:
        balance = get_coinbase_balance()
        if balance is not None:
            print(f"💵 Current Master Balance (Coinbase): ${balance:,.2f}")
    
    print()
    print_divider("=")
    print("  Report complete. For detailed analysis, check:")
    print("  • data/trade_history.json - Completed trades")
    print("  • data/daily_profit_history.json - Daily profit tracking")
    print("  • trade_journal.jsonl - Detailed trade journal")
    print_divider("=")
    print()
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nReport cancelled by user.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
