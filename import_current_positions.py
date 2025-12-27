#!/usr/bin/env python3
"""
Import Current Positions into Position Tracker

This script imports all current Coinbase positions into the position tracker
using their current market prices as the entry prices. This is a one-time
operation to bootstrap the tracker for existing positions.

WARNING: This will record current prices as entry prices, which means:
- Positions currently at a loss will have artificially high entry prices
- Positions currently in profit will have artificially low entry prices
- Future P&L calculations will be relative to TODAY's prices

Use this when:
- Positions exist but aren't tracked (tracker was added after positions opened)
- You want to start fresh with profit-taking from current levels
- You're okay with P&L being calculated from now forward, not from original entry
"""

import os
import sys
import logging

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Import current positions into tracker"""
    try:
        from broker_manager import CoinbaseBroker
        from position_tracker import PositionTracker
        
        logger.info("=" * 80)
        logger.info("IMPORTING CURRENT POSITIONS INTO TRACKER")
        logger.info("=" * 80)
        
        # Initialize broker
        logger.info("\n1. Connecting to Coinbase...")
        broker = CoinbaseBroker()
        if not broker.connect():
            logger.error("Failed to connect to Coinbase")
            return 1
        
        logger.info("✅ Connected to Coinbase")
        
        # Initialize position tracker
        logger.info("\n2. Initializing position tracker...")
        tracker = PositionTracker(storage_file="positions.json")
        logger.info(f"✅ Tracker initialized with {len(tracker.get_all_positions())} existing positions")
        
        # Get current positions from Coinbase
        logger.info("\n3. Fetching current positions from Coinbase...")
        positions = broker.get_positions()
        if not positions:
            logger.warning("No positions found at broker")
            return 0
        
        logger.info(f"✅ Found {len(positions)} positions at broker")
        
        # Import each position
        logger.info("\n4. Importing positions...")
        logger.info("-" * 80)
        
        imported_count = 0
        skipped_count = 0
        error_count = 0
        
        for i, pos in enumerate(positions, 1):
            symbol = pos.get('symbol', 'UNKNOWN')
            quantity = pos.get('quantity', 0)
            currency = pos.get('currency', symbol.split('-')[0] if '-' in symbol else symbol)
            
            try:
                # Get current price
                current_price = broker.get_current_price(symbol)
                if not current_price or current_price == 0:
                    logger.warning(f"[{i}/{len(positions)}] ⚠️ Could not get price for {symbol} - SKIPPED")
                    skipped_count += 1
                    continue
                
                # Calculate position value
                position_value = quantity * current_price
                
                # Skip dust positions (under $0.50)
                if position_value < 0.50:
                    logger.info(f"[{i}/{len(positions)}] ⏭️ {symbol}: ${position_value:.2f} (too small, skipping)")
                    skipped_count += 1
                    continue
                
                # Check if already tracked
                existing = tracker.get_position(symbol)
                if existing:
                    logger.info(f"[{i}/{len(positions)}] ℹ️ {symbol}: Already tracked at ${existing['entry_price']:.2f}")
                    logger.info(f"                Current: ${current_price:.2f}, Qty: {quantity:.8f}, Value: ${position_value:.2f}")
                    
                    # Ask user if they want to override
                    response = input(f"                Override entry price? (y/N): ").strip().lower()
                    if response != 'y':
                        logger.info(f"                Keeping existing entry price")
                        skipped_count += 1
                        continue
                
                # Import position with current price as entry price
                success = tracker.track_entry(
                    symbol=symbol,
                    entry_price=current_price,
                    quantity=quantity,
                    size_usd=position_value,
                    strategy="IMPORTED"
                )
                
                if success:
                    logger.info(f"[{i}/{len(positions)}] ✅ {symbol}: Imported")
                    logger.info(f"                Entry: ${current_price:.2f}, Qty: {quantity:.8f}, Value: ${position_value:.2f}")
                    imported_count += 1
                else:
                    logger.error(f"[{i}/{len(positions)}] ❌ {symbol}: Import failed")
                    error_count += 1
                    
            except Exception as e:
                logger.error(f"[{i}/{len(positions)}] ❌ {symbol}: Error - {e}")
                error_count += 1
        
        # Summary
        logger.info("-" * 80)
        logger.info(f"\n5. Import Summary:")
        logger.info(f"   Total positions:  {len(positions)}")
        logger.info(f"   Imported:         {imported_count}")
        logger.info(f"   Skipped:          {skipped_count}")
        logger.info(f"   Errors:           {error_count}")
        logger.info(f"   Tracked total:    {len(tracker.get_all_positions())}")
        
        logger.info("\n" + "=" * 80)
        logger.info("✅ IMPORT COMPLETE")
        logger.info("=" * 80)
        logger.info("\nNext steps:")
        logger.info("1. Restart the bot to start using tracked positions")
        logger.info("2. Monitor logs for profit-taking exits")
        logger.info("3. Positions will now exit at profit targets (2%, 2.5%, 3%, 4%)")
        
        return 0
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
