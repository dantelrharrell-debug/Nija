#!/usr/bin/env python3
"""
Quick diagnostic script to check where your Coinbase funds are located.
This will show you if funds are in Consumer wallet vs Advanced Trade portfolio.
"""

import os
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseAdvancedTradeBroker

def main():
    logger.info("=" * 80)
    logger.info("🔍 COINBASE BALANCE LOCATION DIAGNOSTIC")
    logger.info("=" * 80)
    logger.info("")
    
    try:
        # Initialize broker
        broker = CoinbaseAdvancedTradeBroker()
        
        # Get balance breakdown
        balance_data = broker.get_account_balance()
        
        consumer_usd = balance_data.get('consumer_usd', 0.0)
        consumer_usdc = balance_data.get('consumer_usdc', 0.0)
        advanced_usd = balance_data.get('usd', 0.0)
        advanced_usdc = balance_data.get('usdc', 0.0)
        trading_balance = balance_data.get('trading_balance', 0.0)
        
        logger.info("")
        logger.info("=" * 80)
        logger.info("📊 BALANCE BREAKDOWN:")
        logger.info("=" * 80)
        logger.info(f"Consumer Wallet USD:         ${consumer_usd:,.2f}  {'⚠️ NOT TRADABLE VIA API' if consumer_usd > 0 else ''}")
        logger.info(f"Consumer Wallet USDC:        ${consumer_usdc:,.2f}  {'⚠️ NOT TRADABLE VIA API' if consumer_usdc > 0 else ''}")
        logger.info(f"Advanced Trade USD:          ${advanced_usd:,.2f}  {'✅ TRADABLE' if advanced_usd > 0 else ''}")
        logger.info(f"Advanced Trade USDC:         ${advanced_usdc:,.2f}  {'✅ TRADABLE' if advanced_usdc > 0 else ''}")
        logger.info("-" * 80)
        logger.info(f"TOTAL TRADABLE BALANCE:      ${trading_balance:,.2f}")
        logger.info("=" * 80)
        logger.info("")
        
        # Diagnosis
        total_consumer = consumer_usd + consumer_usdc
        total_advanced = advanced_usd + advanced_usdc
        
        if trading_balance < 5.0:
            logger.error("❌ PROBLEM DETECTED: Insufficient funds in Advanced Trade!")
            logger.error("")
            
            if total_consumer > 0:
                logger.error(f"🔍 You have ${total_consumer:,.2f} in Consumer wallet but ${total_advanced:,.2f} in Advanced Trade")
                logger.error("   The bot can ONLY trade from Advanced Trade portfolio.")
                logger.error("")
                logger.error("💡 SOLUTION: Transfer funds to Advanced Trade")
                logger.error("   1. Go to: https://www.coinbase.com/advanced-portfolio")
                logger.error("   2. Click 'Deposit' → 'From Coinbase'")
                logger.error("   3. Transfer USD/USDC to Advanced Trade")
                logger.error("   4. Transfer is instant - bot will work immediately after")
            else:
                logger.error("   No funds found in either Consumer or Advanced Trade.")
                logger.error("   You need to deposit funds to Coinbase first.")
            
        else:
            logger.info("✅ SUCCESS: You have sufficient funds in Advanced Trade!")
            logger.info(f"   Your bot can trade with ${trading_balance:,.2f}")
            logger.info("")
            
            if total_consumer > 0:
                logger.info(f"ℹ️  Note: You also have ${total_consumer:,.2f} in Consumer wallet")
                logger.info("   Consider transferring to Advanced Trade for more trading capital.")
        
        logger.info("")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"❌ Error checking balance: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
