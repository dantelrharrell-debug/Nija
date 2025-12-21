#!/usr/bin/env python3
"""
Quick bot restart check - verifies balance and starts trading cycle
"""

import os
import sys
import time
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def main():
    logger.info("=" * 70)
    logger.info("NIJA BOT RESTART CHECK")
    logger.info("=" * 70)
    
    try:
        from trading_strategy import TradingStrategy
        
        logger.info("Initializing trading strategy...")
        strategy = TradingStrategy()
        
        logger.info(f"✅ Strategy initialized")
        logger.info(f"   Account balance: ${strategy.account_balance:,.2f}")
        logger.info(f"   Max positions: {strategy.max_concurrent_positions}")
        logger.info(f"   Open positions: {len(strategy.open_positions)}")
        
        logger.info("")
        logger.info("🚀 Starting trading cycle...")
        logger.info("")
        
        # Run a few cycles
        for cycle in range(1, 6):
            logger.info(f"🔄 Cycle {cycle}/5...")
            try:
                strategy.run_cycle()
                logger.info(f"   ✅ Cycle {cycle} complete")
            except Exception as e:
                logger.error(f"   ❌ Cycle {cycle} failed: {e}")
            
            time.sleep(2)
        
        logger.info("")
        logger.info("=" * 70)
        logger.info("✅ BOT RESTART CHECK COMPLETE")
        logger.info("=" * 70)
        
    except Exception as e:
        logger.error(f"❌ FAILED: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
