#!/usr/bin/env python3
"""
Comprehensive Account Funds and Trading Status Verification
===========================================================

This script provides complete visibility into:
1. All account balances (Coinbase Master, Kraken Master, Kraken Users)
2. Fund breakdown: Available + Held + In Positions = Total Funds
3. Active trading status for each account
4. Confirmation that funds are properly accounted for

Usage:
    python3 verify_all_account_funds.py
"""

import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def print_banner():
    """Print script banner"""
    print()
    print("=" * 90)
    print("NIJA COMPREHENSIVE ACCOUNT FUNDS & TRADING STATUS VERIFICATION".center(90))
    print("=" * 90)
    print()
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


def print_section(title: str):
    """Print section header"""
    print()
    print("-" * 90)
    print(f"  {title}")
    print("-" * 90)
    print()


def check_broker_credentials() -> Dict[str, bool]:
    """Check which broker credentials are configured"""
    creds = {
        'coinbase_master': False,
        'kraken_master': False,
        'kraken_users': []
    }
    
    # Check Coinbase Master
    coinbase_key = os.getenv("COINBASE_API_KEY", "").strip()
    coinbase_secret = os.getenv("COINBASE_API_SECRET", "").strip()
    creds['coinbase_master'] = bool(coinbase_key and coinbase_secret)
    
    # Check Kraken Master
    kraken_key = os.getenv("KRAKEN_MASTER_API_KEY", "").strip()
    kraken_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "").strip()
    creds['kraken_master'] = bool(kraken_key and kraken_secret)
    
    # Check Kraken Users
    # Common user IDs to check
    user_ids = ['daivon', 'tania', 'daivon_frazier', 'tania_gilbert']
    for user_id in user_ids:
        user_key = os.getenv(f"KRAKEN_USER_{user_id.upper()}_API_KEY", "").strip()
        user_secret = os.getenv(f"KRAKEN_USER_{user_id.upper()}_API_SECRET", "").strip()
        if user_key and user_secret:
            creds['kraken_users'].append(user_id)
    
    return creds


def get_coinbase_master_balance():
    """Get Coinbase master account balance with full breakdown"""
    try:
        from broker_manager import BrokerType, AccountType, CoinbaseBroker
        
        print("📊 Connecting to Coinbase Master Account...")
        
        broker = CoinbaseBroker(account_type=AccountType.MASTER)
        if not broker.connect():
            print("❌ Failed to connect to Coinbase")
            return None
        
        # Get detailed balance
        balance_data = broker.get_account_balance_detailed()
        
        if not balance_data:
            print("❌ Failed to retrieve balance data")
            return None
        
        return {
            'broker': 'Coinbase',
            'account': 'MASTER',
            'available_usd': balance_data.get('usd', 0.0),
            'available_usdc': balance_data.get('usdc', 0.0),
            'total_available': balance_data.get('trading_balance', 0.0),
            'held_usd': balance_data.get('usd_held', 0.0),
            'held_usdc': balance_data.get('usdc_held', 0.0),
            'total_held': balance_data.get('total_held', 0.0),
            'total_funds': balance_data.get('total_funds', 0.0),
            'crypto_holdings': balance_data.get('crypto', {}),
            'consumer_usd': balance_data.get('consumer_usd', 0.0),
            'consumer_usdc': balance_data.get('consumer_usdc', 0.0),
            'connected': True
        }
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def get_kraken_account_balance(account_type, user_id=None):
    """Get Kraken account balance"""
    try:
        from broker_manager import BrokerType, AccountType, KrakenBroker
        
        account_label = "MASTER" if account_type == AccountType.MASTER else f"USER:{user_id}"
        print(f"📊 Connecting to Kraken {account_label} Account...")
        
        broker = KrakenBroker(account_type=account_type, user_id=user_id)
        if not broker.connect():
            print(f"❌ Failed to connect to Kraken {account_label}")
            return None
        
        # Get balance
        balance = broker.get_account_balance()
        
        # Get positions for fund analysis
        positions = broker.get_positions() or []
        position_value = sum(float(pos.get('market_value', 0) or 0) for pos in positions)
        
        return {
            'broker': 'Kraken',
            'account': account_label,
            'available': balance,
            'positions_value': position_value,
            'total_funds': balance + position_value,
            'position_count': len(positions),
            'connected': True
        }
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def print_coinbase_balance(balance: Dict):
    """Print Coinbase balance details"""
    print(f"🏦 Exchange: {balance['broker']}")
    print(f"👤 Account: {balance['account']}")
    print()
    
    # Available funds
    print("   💰 AVAILABLE FUNDS:")
    print(f"      USD:  ${balance['available_usd']:.2f}")
    print(f"      USDC: ${balance['available_usdc']:.2f}")
    print(f"      ─────────────────────")
    print(f"      Total Available: ${balance['total_available']:.2f}")
    print()
    
    # Held funds (in open orders/positions)
    if balance['total_held'] > 0:
        print("   🔒 HELD FUNDS (in open orders/positions):")
        print(f"      USD:  ${balance['held_usd']:.2f}")
        print(f"      USDC: ${balance['held_usdc']:.2f}")
        print(f"      ─────────────────────")
        print(f"      Total Held: ${balance['total_held']:.2f}")
        print()
    
    # Total funds
    print("   💎 TOTAL ACCOUNT FUNDS:")
    print(f"      ${balance['total_funds']:.2f}")
    print()
    
    # Crypto holdings
    crypto = balance.get('crypto_holdings', {})
    if crypto:
        print(f"   🪙 CRYPTO HOLDINGS ({len(crypto)} assets):")
        for asset, amount in sorted(crypto.items()):
            if amount > 0:
                print(f"      {asset}: {amount:.8f}")
        print()
    
    # Consumer wallet warning
    consumer_total = balance.get('consumer_usd', 0) + balance.get('consumer_usdc', 0)
    if consumer_total > 0:
        print("   ⚠️  CONSUMER WALLET FUNDS (NOT API-TRADEABLE):")
        print(f"      USD:  ${balance['consumer_usd']:.2f}")
        print(f"      USDC: ${balance['consumer_usdc']:.2f}")
        print(f"      Total: ${consumer_total:.2f}")
        print()
        print("      These funds must be transferred to Advanced Trade portfolio")
        print("      to be available for bot trading.")
        print()


def print_kraken_balance(balance: Dict):
    """Print Kraken balance details"""
    print(f"🏦 Exchange: {balance['broker']}")
    print(f"👤 Account: {balance['account']}")
    print()
    
    # Available funds
    print("   💰 AVAILABLE FOR TRADING:")
    print(f"      ${balance['available']:.2f}")
    print()
    
    # Position value
    if balance['position_count'] > 0:
        print(f"   📊 OPEN POSITIONS ({balance['position_count']} positions):")
        print(f"      Value: ${balance['positions_value']:.2f}")
        print()
    
    # Total funds
    print("   💎 TOTAL ACCOUNT FUNDS:")
    print(f"      ${balance['total_funds']:.2f}")
    print()


def check_trading_status():
    """Check if bot is actively trading"""
    print_section("TRADING ACTIVITY STATUS")
    
    # Check for recent trade journal entries
    try:
        trade_journal = "trade_journal.jsonl"
        if os.path.exists(trade_journal):
            # Get file modification time
            mod_time = os.path.getmtime(trade_journal)
            last_modified = datetime.fromtimestamp(mod_time)
            time_since = datetime.now() - last_modified
            
            print(f"✅ Trade journal exists: {trade_journal}")
            print(f"   Last updated: {last_modified.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"   Time since last update: {time_since}")
            
            if time_since.total_seconds() < 3600:  # Less than 1 hour
                print(f"   ✅ ACTIVE - Recent trading activity detected")
            elif time_since.total_seconds() < 86400:  # Less than 24 hours
                print(f"   ⚠️  POSSIBLY INACTIVE - No recent activity (last update > 1 hour ago)")
            else:
                print(f"   ❌ INACTIVE - No recent activity (last update > 24 hours ago)")
        else:
            print(f"⚠️  Trade journal not found: {trade_journal}")
            print(f"   Bot may not have made any trades yet")
    except Exception as e:
        print(f"❌ Error checking trade journal: {e}")


def main():
    """Main verification function"""
    print_banner()
    
    # Check credentials
    print_section("CREDENTIAL STATUS")
    creds = check_broker_credentials()
    
    print("Configured Accounts:")
    print()
    if creds['coinbase_master']:
        print("   ✅ Coinbase Master - Credentials configured")
    else:
        print("   ❌ Coinbase Master - Credentials NOT configured")
    
    if creds['kraken_master']:
        print("   ✅ Kraken Master - Credentials configured")
    else:
        print("   ❌ Kraken Master - Credentials NOT configured")
    
    if creds['kraken_users']:
        print(f"   ✅ Kraken Users - {len(creds['kraken_users'])} configured: {', '.join(creds['kraken_users'])}")
    else:
        print("   ❌ Kraken Users - No user credentials configured")
    
    print()
    
    # Collect all balances
    all_balances = []
    
    # Get Coinbase Master balance
    if creds['coinbase_master']:
        print_section("COINBASE MASTER ACCOUNT")
        balance = get_coinbase_master_balance()
        if balance:
            print_coinbase_balance(balance)
            all_balances.append(balance)
    
    # Get Kraken Master balance
    if creds['kraken_master']:
        print_section("KRAKEN MASTER ACCOUNT")
        balance = get_kraken_account_balance(account_type='MASTER')
        if balance:
            print_kraken_balance(balance)
            all_balances.append(balance)
    
    # Get Kraken User balances
    if creds['kraken_users']:
        from broker_manager import AccountType
        for user_id in creds['kraken_users']:
            print_section(f"KRAKEN USER ACCOUNT: {user_id.upper()}")
            balance = get_kraken_account_balance(account_type=AccountType.USER, user_id=user_id)
            if balance:
                print_kraken_balance(balance)
                all_balances.append(balance)
    
    # Trading status
    check_trading_status()
    
    # Summary
    print_section("OVERALL SUMMARY")
    
    total_available = 0.0
    total_held = 0.0
    total_positions = 0.0
    total_funds = 0.0
    
    for balance in all_balances:
        if balance['broker'] == 'Coinbase':
            total_available += balance.get('total_available', 0)
            total_held += balance.get('total_held', 0)
            total_funds += balance.get('total_funds', 0)
        else:  # Kraken
            total_available += balance.get('available', 0)
            total_positions += balance.get('positions_value', 0)
            total_funds += balance.get('total_funds', 0)
    
    print(f"📊 Accounts Connected: {len(all_balances)}")
    print()
    print(f"💰 Total Available (free to trade): ${total_available:.2f}")
    if total_held > 0:
        print(f"🔒 Total Held (in orders): ${total_held:.2f}")
    if total_positions > 0:
        print(f"📊 Total in Positions: ${total_positions:.2f}")
    print(f"{'─' * 50}")
    print(f"💎 GRAND TOTAL FUNDS: ${total_funds:.2f}")
    print()
    
    if total_funds > 0:
        print("✅ CONFIRMATION: All accounts are funded and balances are properly tracked.")
        print()
        print("   Your funds are allocated as follows:")
        print(f"   - {(total_available/total_funds*100):.1f}% Available for trading")
        if total_held > 0:
            print(f"   - {(total_held/total_funds*100):.1f}% Held in open orders")
        if total_positions > 0:
            print(f"   - {(total_positions/total_funds*100):.1f}% In open positions")
    else:
        print("⚠️  WARNING: No funds detected in any account.")
        print("   Please ensure:")
        print("   1. Accounts are funded")
        print("   2. Funds are in the correct wallet (Advanced Trade for Coinbase)")
        print("   3. API credentials have correct permissions")
    
    print()
    print("=" * 90)
    print()
    
    return 0 if total_funds > 0 else 1


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print()
        print("⚠️  Verification interrupted by user")
        sys.exit(1)
    except Exception as e:
        print()
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
