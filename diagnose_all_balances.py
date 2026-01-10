#!/usr/bin/env python3
"""
Diagnostic script to check ALL account balances across all brokers.
This will help identify where the $28 in Coinbase actually is.
"""

import os
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def check_coinbase_balance():
    """Check Coinbase Advanced Trade balance in detail"""
    try:
        from broker_manager import CoinbaseBroker
        
        logger.info("=" * 80)
        logger.info("🔍 COINBASE ADVANCED TRADE DIAGNOSTIC")
        logger.info("=" * 80)
        
        broker = CoinbaseBroker()
        if not broker.connect():
            logger.error("❌ Failed to connect to Coinbase")
            return
        
        # Get detailed balance
        balance_info = broker.get_account_balance_detailed()
        
        logger.info("\n📊 COINBASE BALANCE BREAKDOWN:")
        logger.info(f"   USD (Advanced Trade): ${balance_info.get('usd', 0):.2f}")
        logger.info(f"   USDC (Advanced Trade): ${balance_info.get('usdc', 0):.2f}")
        logger.info(f"   Total Trading Balance: ${balance_info.get('trading_balance', 0):.2f}")
        logger.info(f"   Consumer USD: ${balance_info.get('consumer_usd', 0):.2f}")
        logger.info(f"   Consumer USDC: ${balance_info.get('consumer_usdc', 0):.2f}")
        
        crypto = balance_info.get('crypto', {})
        if crypto:
            logger.info(f"\n   💎 Crypto Holdings:")
            for currency, amount in crypto.items():
                logger.info(f"      {currency}: {amount}")
        
        total_consumer = balance_info.get('consumer_usd', 0) + balance_info.get('consumer_usdc', 0)
        total_all = balance_info.get('trading_balance', 0) + total_consumer
        
        logger.info(f"\n📈 SUMMARY:")
        logger.info(f"   Advanced Trade Total: ${balance_info.get('trading_balance', 0):.2f} ✅ (API TRADABLE)")
        logger.info(f"   Consumer Wallet Total: ${total_consumer:.2f} ❌ (NOT API TRADABLE)")
        logger.info(f"   GRAND TOTAL: ${total_all:.2f}")
        
        if balance_info.get('trading_balance', 0) < 28 and total_consumer > 0:
            logger.warning("\n⚠️  FUNDS IN CONSUMER WALLET DETECTED!")
            logger.warning("   The bot cannot trade with Consumer wallet funds.")
            logger.warning("   Transfer to Advanced Trade: https://www.coinbase.com/advanced-portfolio")
        
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"❌ Coinbase diagnostic failed: {e}")
        import traceback
        traceback.print_exc()

def check_kraken_balance():
    """Check Kraken balance"""
    try:
        from broker_manager import KrakenBroker, AccountType
        
        logger.info("\n" + "=" * 80)
        logger.info("🔍 KRAKEN MASTER DIAGNOSTIC")
        logger.info("=" * 80)
        
        broker = KrakenBroker(account_type=AccountType.MASTER)
        if not broker.connect():
            logger.error("❌ Failed to connect to Kraken Master")
            logger.error("   Check KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET")
            return
        
        balance = broker.get_account_balance()
        logger.info(f"\n💰 Kraken Master Balance: ${balance:.2f}")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"❌ Kraken diagnostic failed: {e}")
        import traceback
        traceback.print_exc()

def check_alpaca_balance():
    """Check Alpaca paper trading balance"""
    try:
        from broker_manager import AlpacaBroker
        
        logger.info("\n" + "=" * 80)
        logger.info("🔍 ALPACA PAPER TRADING DIAGNOSTIC")
        logger.info("=" * 80)
        
        broker = AlpacaBroker()
        if not broker.connect():
            logger.error("❌ Failed to connect to Alpaca")
            logger.error("   Check ALPACA_API_KEY and ALPACA_API_SECRET")
            return
        
        balance = broker.get_account_balance()
        logger.info(f"\n💰 Alpaca Paper Trading Balance: ${balance:.2f}")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"❌ Alpaca diagnostic failed: {e}")
        import traceback
        traceback.print_exc()

def check_user1_balance():
    """Check User #1 (Daivon Frazier) Kraken balance"""
    try:
        from broker_manager import KrakenBroker, AccountType
        
        logger.info("\n" + "=" * 80)
        logger.info("🔍 USER #1 (DAIVON FRAZIER) KRAKEN DIAGNOSTIC")
        logger.info("=" * 80)
        
        broker = KrakenBroker(account_type=AccountType.USER, user_id="daivon_frazier")
        if not broker.connect():
            logger.error("❌ Failed to connect to User #1 Kraken")
            logger.error("   Check KRAKEN_USER_DAIVON_API_KEY and KRAKEN_USER_DAIVON_API_SECRET")
            return
        
        balance = broker.get_account_balance()
        logger.info(f"\n💰 User #1 (Daivon Frazier) Kraken Balance: ${balance:.2f}")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"❌ User #1 diagnostic failed: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Run all diagnostics"""
    logger.info("\n" + "🔬" * 40)
    logger.info("NIJA MULTI-BROKER BALANCE DIAGNOSTIC")
    logger.info("🔬" * 40 + "\n")
    
    logger.info("Expected balances (as reported by user):")
    logger.info("  • Master Coinbase: $28")
    logger.info("  • Master Kraken: $28")
    logger.info("  • Master Alpaca (Paper): $100,000")
    logger.info("  • User #1 Kraken: $30")
    logger.info("")
    
    # Check each broker
    check_coinbase_balance()
    check_kraken_balance()
    check_alpaca_balance()
    check_user1_balance()
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ DIAGNOSTIC COMPLETE")
    logger.info("=" * 80)
    logger.info("\nNext steps:")
    logger.info("  1. If Coinbase shows funds in Consumer wallet → Transfer to Advanced Trade")
    logger.info("  2. If Kraken shows 'Invalid nonce' → Regenerate API keys")
    logger.info("  3. If any connection fails → Check API credentials in .env file")
    logger.info("=" * 80 + "\n")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n\n⚠️  Diagnostic interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"\n❌ Diagnostic failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
