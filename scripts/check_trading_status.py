#!/usr/bin/env python3
"""
NIJA Trading Status and Profit Report
======================================

Checks if NIJA is trading for master and user accounts, and calculates profits.

This script:
1. Checks if platform account is connected and trading
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


def _normalize_user_tokens(user_id: str) -> tuple[str, str]:
    """Return (firstname_token, full_token) for env-var credential lookup."""
    normalized = str(user_id or "").strip().lower()
    parts = [p for p in normalized.split('_') if p]
    first = (parts[0] if parts else normalized).upper()
    full = "_".join(parts).upper() if parts else normalized.upper()
    return first, full


def _resolve_user_env_pair(user_id: str, broker_prefix: str) -> tuple[str, str]:
    """Resolve user credential env names with full-name fallback support."""
    first, full = _normalize_user_tokens(user_id)
    candidates = [
        (f"{broker_prefix}_USER_{full}_API_KEY", f"{broker_prefix}_USER_{full}_API_SECRET"),
        (f"{broker_prefix}_USER_{first}_API_KEY", f"{broker_prefix}_USER_{first}_API_SECRET"),
    ]
    for key_name, sec_name in candidates:
        if os.getenv(key_name) and os.getenv(sec_name):
            return key_name, sec_name
    return candidates[-1]


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
    if os.getenv('COINBASE_API_KEY') and (os.getenv('COINBASE_API_SECRET') or os.getenv('COINBASE_PEM_CONTENT')):
        credentials['coinbase'] = True

    # Kraken
    if os.getenv('KRAKEN_PLATFORM_API_KEY') and os.getenv('KRAKEN_PLATFORM_API_SECRET'):
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


def load_user_configs() -> dict:
    """Load user configurations from config files."""
    users = {}

    # Try to load from config files
    user_config_dir = Path("config/users")
    if user_config_dir.exists():
        for config_file in user_config_dir.glob("*.json"):
            if config_file.name == "README.md":
                continue
            try:
                with open(config_file, 'r') as f:
                    user_list = json.load(f)
                    if isinstance(user_list, list):
                        for user in user_list:
                            if user.get('enabled'):
                                user_id = user.get('user_id')
                                broker = user.get('broker_type')
                                if user_id and broker:
                                    if user_id not in users:
                                        users[user_id] = {}
                                    users[user_id][broker] = False  # Will check creds below
            except Exception as e:
                logger.warning(f"Error loading user config {config_file}: {e}")

    # Fallback to hardcoded users if no config files
    if not users:
        users = {
            'daivon_frazier': {'kraken': False, 'alpaca': False},
            'tania_gilbert': {'kraken': False, 'alpaca': False}
        }

    return users


def check_user_credentials() -> dict:
    """Check which users have credentials configured."""
    users = load_user_configs()

    # Check credentials for each user
    for user_id in list(users.keys()):
        # Check Kraken credentials
        if 'kraken' in users[user_id]:
            kraken_key, kraken_secret = _resolve_user_env_pair(user_id, 'KRAKEN')
            if os.getenv(kraken_key) and os.getenv(kraken_secret):
                users[user_id]['kraken'] = True

        # Check Alpaca credentials
        if 'alpaca' in users[user_id]:
            alpaca_key, alpaca_secret = _resolve_user_env_pair(user_id, 'ALPACA')
            if os.getenv(alpaca_key) and os.getenv(alpaca_secret):
                users[user_id]['alpaca'] = True

    return users


def get_coinbase_balance() -> float:
    """Get Coinbase balance for platform account."""
    try:
        try:
            from coinbase.rest import RESTClient
        except ImportError:
            logger.warning("coinbase package not installed, cannot retrieve balance")
            return None

        api_key = os.getenv('COINBASE_API_KEY')
        api_secret = os.getenv('COINBASE_API_SECRET') or os.getenv('COINBASE_PEM_CONTENT')

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


def get_kraken_balance(api_key: str, api_secret: str) -> float:
    """Fetch Kraken USD/USDC available balance via krakenex."""
    if not api_key or not api_secret:
        return None
    try:
        import krakenex  # type: ignore

        client = krakenex.API(key=api_key, secret=api_secret)
        resp = client.query_private("Balance")
        if isinstance(resp, dict) and resp.get("error"):
            return None
        result = (resp or {}).get("result", {}) if isinstance(resp, dict) else {}
        usd = float(result.get("ZUSD") or result.get("USD") or 0.0)
        usdc = float(result.get("USDC") or 0.0)
        return usd + usdc
    except Exception as e:
        logger.warning(f"Error getting Kraken balance: {e}")
        return None


def get_platform_kraken_balance() -> float:
    """Fetch platform Kraken balance from platform/legacy env vars."""
    api_key = os.getenv("KRAKEN_PLATFORM_API_KEY") or os.getenv("KRAKEN_API_KEY")
    api_secret = os.getenv("KRAKEN_PLATFORM_API_SECRET") or os.getenv("KRAKEN_API_SECRET")
    return get_kraken_balance(api_key, api_secret)


def get_user_kraken_balance(user_id: str) -> float:
    """Fetch Kraken balance for a specific configured user account."""
    key_name, sec_name = _resolve_user_env_pair(user_id, "KRAKEN")
    return get_kraken_balance(os.getenv(key_name), os.getenv(sec_name))


# Constants
MAX_RECENT_TRADES = 20  # Maximum number of recent trades to display


def load_trade_history() -> dict:
    """Load trade history from data files."""
    history = {
        'total_trades': 0,
        'profitable_trades': 0,
        'losing_trades': 0,
        'breakeven_trades': 0,
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
                            elif profit < 0:
                                history['losing_trades'] += 1
                            else:
                                history['breakeven_trades'] += 1
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
                history['recent_trades'] = journal_trades[-MAX_RECENT_TRADES:]
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
    print_section_header("PLATFORM ACCOUNT (NIJA System)")
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
        print("\n💰 Platform Account Balance (Coinbase):")
        balance = get_coinbase_balance()
        if balance is not None:
            print(f"   Total: ${balance:,.2f} USD")
        else:
            print("   ⚠️  Could not retrieve balance")

    if master_creds['kraken']:
        print("\n💰 Platform Account Balance (Kraken):")
        kraken_balance = get_platform_kraken_balance()
        if kraken_balance is not None:
            print(f"   Total: ${kraken_balance:,.2f} USD")
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

        if brokers.get('kraken'):
            user_balance = get_user_kraken_balance(user_id)
            if user_balance is not None:
                print(f"   💰 KRAKEN BALANCE: ${user_balance:,.2f} USD")
            else:
                print("   ⚠️  KRAKEN BALANCE: unavailable")

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
    if trade_history['breakeven_trades'] > 0:
        print(f"   Breakeven Trades: {trade_history['breakeven_trades']}")

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
        print(f"✅ YES - Platform account is configured to trade on {master_connected_count} broker(s):")
        for broker in master_trading_brokers:
            print(f"   • {broker}")
    else:
        print("❌ NO - Platform account has no broker credentials configured")

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
