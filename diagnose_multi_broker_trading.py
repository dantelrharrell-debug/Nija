#!/usr/bin/env python3
"""
Multi-Broker Trading Diagnostic Script
=======================================

This script diagnoses why NIJA might only be trading on one exchange
when multiple exchanges are connected and funded.

It checks:
1. Exchange credentials configuration
2. Broker connection status  
3. Account balances across all exchanges
4. Independent trading configuration
5. Funded broker detection logic
6. Trading thread status

Run this to understand which exchanges are ready to trade and why
some might not be trading even though they're connected.
"""

import os
import sys
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def check_credentials():
    """Check which exchange credentials are configured"""
    logger.info("=" * 80)
    logger.info("🔍 CHECKING EXCHANGE CREDENTIALS")
    logger.info("=" * 80)
    
    exchanges = {
        'Coinbase Master': ['COINBASE_API_KEY', 'COINBASE_API_SECRET'],
        'Kraken Master': ['KRAKEN_MASTER_API_KEY', 'KRAKEN_MASTER_API_SECRET'],
        'Kraken User Daivon': ['KRAKEN_USER_DAIVON_API_KEY', 'KRAKEN_USER_DAIVON_API_SECRET'],
        'Kraken User Tania': ['KRAKEN_USER_TANIA_API_KEY', 'KRAKEN_USER_TANIA_API_SECRET'],
        'OKX': ['OKX_API_KEY', 'OKX_API_SECRET', 'OKX_PASSPHRASE'],
        'Binance': ['BINANCE_API_KEY', 'BINANCE_API_SECRET'],
        'Alpaca': ['ALPACA_API_KEY', 'ALPACA_API_SECRET'],
    }
    
    configured = []
    for exchange, vars in exchanges.items():
        all_set = all(os.getenv(var) for var in vars)
        if all_set:
            logger.info(f"✅ {exchange}: Credentials configured")
            configured.append(exchange)
        else:
            missing = [var for var in vars if not os.getenv(var)]
            logger.info(f"❌ {exchange}: Missing {', '.join(missing)}")
    
    logger.info("=" * 80)
    logger.info(f"📊 SUMMARY: {len(configured)} exchange(s) configured")
    logger.info("=" * 80)
    return configured

def check_broker_connections():
    """Check which brokers can actually connect"""
    logger.info("")
    logger.info("=" * 80)
    logger.info("🔌 CHECKING BROKER CONNECTIONS")
    logger.info("=" * 80)
    
    try:
        from broker_manager import (
            CoinbaseBroker, KrakenBroker, OKXBroker,
            BrokerType, AccountType
        )
        from multi_account_broker_manager import MultiAccountBrokerManager
    except ImportError as e:
        logger.error(f"❌ Failed to import broker modules: {e}")
        return {}, {}
    
    master_brokers = {}
    user_brokers = {}
    
    # Test Coinbase Master
    logger.info("📊 Testing Coinbase Master connection...")
    try:
        coinbase = CoinbaseBroker()
        if coinbase.connect():
            balance = coinbase.get_account_balance()
            master_brokers['coinbase'] = balance
            logger.info(f"   ✅ Connected - Balance: ${balance:,.2f}")
        else:
            logger.warning(f"   ❌ Connection failed")
    except Exception as e:
        logger.warning(f"   ❌ Error: {e}")
    
    # Test Kraken Master
    logger.info("📊 Testing Kraken Master connection...")
    try:
        kraken = KrakenBroker(account_type=AccountType.MASTER)
        if kraken.connect():
            balance = kraken.get_account_balance()
            master_brokers['kraken'] = balance
            logger.info(f"   ✅ Connected - Balance: ${balance:,.2f}")
        else:
            logger.warning(f"   ❌ Connection failed")
    except Exception as e:
        logger.warning(f"   ❌ Error: {e}")
    
    # Test OKX
    logger.info("📊 Testing OKX connection...")
    try:
        okx = OKXBroker()
        if okx.connect():
            balance = okx.get_account_balance()
            master_brokers['okx'] = balance
            logger.info(f"   ✅ Connected - Balance: ${balance:,.2f}")
        else:
            logger.warning(f"   ❌ Connection failed")
    except Exception as e:
        logger.warning(f"   ❌ Error: {e}")
    
    # Test Kraken User Accounts
    user_configs = [
        ('daivon_frazier', 'DAIVON'),
        ('tania_gilbert', 'TANIA'),
    ]
    
    for user_id, user_env_name in user_configs:
        logger.info(f"👤 Testing Kraken User ({user_id}) connection...")
        try:
            kraken_user = KrakenBroker(account_type=AccountType.USER, user_id=user_id)
            if kraken_user.connect():
                balance = kraken_user.get_account_balance()
                if user_id not in user_brokers:
                    user_brokers[user_id] = {}
                user_brokers[user_id]['kraken'] = balance
                logger.info(f"   ✅ Connected - Balance: ${balance:,.2f}")
            else:
                logger.warning(f"   ❌ Connection failed")
        except Exception as e:
            logger.warning(f"   ❌ Error: {e}")
    
    logger.info("=" * 80)
    logger.info(f"📊 MASTER BROKERS CONNECTED: {len(master_brokers)}")
    for broker, balance in master_brokers.items():
        logger.info(f"   • {broker.upper()}: ${balance:,.2f}")
    
    if user_brokers:
        logger.info(f"👥 USER BROKERS CONNECTED: {sum(len(brokers) for brokers in user_brokers.values())}")
        for user_id, brokers in user_brokers.items():
            for broker, balance in brokers.items():
                logger.info(f"   • {user_id} ({broker}): ${balance:,.2f}")
    
    logger.info("=" * 80)
    return master_brokers, user_brokers

def check_funded_status(master_brokers, user_brokers):
    """Check which brokers meet the minimum funding threshold"""
    logger.info("")
    logger.info("=" * 80)
    logger.info("💰 CHECKING FUNDED STATUS")
    logger.info("=" * 80)
    
    MINIMUM_FUNDED_BALANCE = 1.0
    
    funded_masters = {}
    funded_users = {}
    
    logger.info(f"Minimum balance for trading: ${MINIMUM_FUNDED_BALANCE:.2f}")
    logger.info("")
    
    logger.info("MASTER ACCOUNTS:")
    for broker, balance in master_brokers.items():
        if balance >= MINIMUM_FUNDED_BALANCE:
            funded_masters[broker] = balance
            logger.info(f"   ✅ {broker.upper()}: ${balance:,.2f} - FUNDED")
        else:
            logger.warning(f"   ❌ {broker.upper()}: ${balance:,.2f} - UNDERFUNDED")
    
    if user_brokers:
        logger.info("")
        logger.info("USER ACCOUNTS:")
        for user_id, brokers in user_brokers.items():
            for broker, balance in brokers.items():
                if balance >= MINIMUM_FUNDED_BALANCE:
                    if user_id not in funded_users:
                        funded_users[user_id] = {}
                    funded_users[user_id][broker] = balance
                    logger.info(f"   ✅ {user_id} ({broker}): ${balance:,.2f} - FUNDED")
                else:
                    logger.warning(f"   ❌ {user_id} ({broker}): ${balance:,.2f} - UNDERFUNDED")
    
    logger.info("=" * 80)
    logger.info(f"📊 FUNDED MASTERS: {len(funded_masters)}")
    if funded_users:
        total_funded_users = sum(len(brokers) for brokers in funded_users.values())
        logger.info(f"👥 FUNDED USERS: {total_funded_users}")
    logger.info("=" * 80)
    
    return funded_masters, funded_users

def check_independent_trading_config():
    """Check if independent multi-broker trading is enabled"""
    logger.info("")
    logger.info("=" * 80)
    logger.info("⚙️  CHECKING INDEPENDENT TRADING CONFIGURATION")
    logger.info("=" * 80)
    
    multi_broker_enabled = os.getenv("MULTI_BROKER_INDEPENDENT", "true")
    logger.info(f"MULTI_BROKER_INDEPENDENT: {multi_broker_enabled}")
    
    enabled = multi_broker_enabled.lower() in ["true", "1", "yes"]
    
    if enabled:
        logger.info("✅ Independent multi-broker trading is ENABLED")
        logger.info("   Each exchange will trade independently in isolated threads")
    else:
        logger.warning("❌ Independent multi-broker trading is DISABLED")
        logger.warning("   Only the primary broker will trade (single-broker mode)")
        logger.warning("   To enable, set: MULTI_BROKER_INDEPENDENT=true")
    
    logger.info("=" * 80)
    return enabled

def main():
    """Run complete diagnostic"""
    logger.info("")
    logger.info("╔" + "═" * 78 + "╗")
    logger.info("║" + " " * 15 + "NIJA MULTI-BROKER TRADING DIAGNOSTIC" + " " * 27 + "║")
    logger.info("╚" + "═" * 78 + "╝")
    logger.info("")
    
    # 1. Check credentials
    configured = check_credentials()
    
    # 2. Check broker connections and balances
    master_brokers, user_brokers = check_broker_connections()
    
    # 3. Check funded status
    funded_masters, funded_users = check_funded_status(master_brokers, user_brokers)
    
    # 4. Check independent trading configuration
    independent_enabled = check_independent_trading_config()
    
    # 5. Final diagnosis
    logger.info("")
    logger.info("=" * 80)
    logger.info("🔬 DIAGNOSIS & RECOMMENDATIONS")
    logger.info("=" * 80)
    
    total_funded = len(funded_masters) + sum(len(brokers) for brokers in funded_users.values())
    
    if total_funded == 0:
        logger.error("❌ CRITICAL: NO FUNDED ACCOUNTS")
        logger.error("   No exchanges have sufficient balance to trade (minimum $1.00)")
        logger.error("")
        logger.error("   ACTION REQUIRED:")
        logger.error("   1. Fund at least one exchange account with $1.00 or more")
        logger.error("   2. Wait a few minutes for balance to appear")
        logger.error("   3. Restart the bot")
    
    elif total_funded == 1:
        single_broker = list(funded_masters.keys())[0] if funded_masters else list(funded_users.values())[0]
        logger.warning(f"⚠️  ONLY ONE FUNDED ACCOUNT: {single_broker}")
        logger.warning("   Trading will occur on only one exchange")
        logger.warning("")
        logger.warning("   RECOMMENDATION:")
        logger.warning("   1. Fund additional exchange accounts for:")
        logger.warning("      • Better diversification")
        logger.warning("      • Reduced API rate limiting")
        logger.warning("      • More resilient trading")
        logger.warning("   2. Restart the bot after funding")
    
    elif not independent_enabled:
        logger.error("❌ PROBLEM FOUND: Multi-broker trading disabled")
        logger.error(f"   You have {total_funded} funded account(s) but independent trading is OFF")
        logger.error("")
        logger.error("   FIX:")
        logger.error("   1. Set environment variable: MULTI_BROKER_INDEPENDENT=true")
        logger.error("   2. Restart the bot")
        logger.error("")
        logger.error("   Without this, only the primary broker (usually Coinbase) trades")
    
    else:
        logger.info("✅ ALL CHECKS PASSED")
        logger.info(f"   • {len(configured)} exchange(s) configured")
        logger.info(f"   • {len(funded_masters)} master account(s) funded")
        if funded_users:
            total_user_accounts = sum(len(brokers) for brokers in funded_users.values())
            logger.info(f"   • {total_user_accounts} user account(s) funded")
        logger.info(f"   • Independent trading: ENABLED")
        logger.info("")
        logger.info("   ✨ EXPECTED BEHAVIOR:")
        logger.info("   • Each funded exchange should trade independently")
        logger.info("   • Trading threads spawn for each exchange")
        logger.info("   • Failures on one exchange don't affect others")
        logger.info("")
        logger.info("   If trading is still only happening on one exchange:")
        logger.info("   1. Check bot.py startup logs for 'STARTING INDEPENDENT MULTI-BROKER TRADING MODE'")
        logger.info("   2. Look for 'Started independent trading thread for...' messages")
        logger.info("   3. Check for errors in trading thread initialization")
        logger.info("   4. Verify balances haven't dropped below $1.00")
        logger.info("   5. Review logs for exchange-specific errors (API permissions, nonce, etc.)")
    
    logger.info("=" * 80)
    logger.info("")
    logger.info("💡 For more help:")
    logger.info("   • See MULTI_EXCHANGE_TRADING_GUIDE.md")
    logger.info("   • Check KRAKEN_NOT_CONNECTING_DIAGNOSIS.md for Kraken issues")
    logger.info("   • Review bot logs: tail -f nija.log")
    logger.info("")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Diagnostic interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n\n❌ Diagnostic failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
