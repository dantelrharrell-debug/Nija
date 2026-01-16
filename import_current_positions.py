#!/usr/bin/env python3
"""
Import Current Positions to Position Tracker
=============================================

This script imports all current broker positions into the position tracker.
It estimates entry prices using current price as a baseline.

This is useful for:
1. Positions that were entered before position tracking was implemented
2. Positions that lost tracking data due to errors
3. Migrating from manual trades to bot-tracked trades

NOTE: Entry prices will be ESTIMATED at current market price.
This means P&L calculations will start from zero.
The bot will use aggressive technical exits for these positions.

Usage:
    python3 import_current_positions.py

The script will:
- Connect to all configured brokers
- Get all open positions
- Import them to position_tracker with estimated entry prices
- Report summary of imported positions
"""

import os
import sys
import logging
from datetime import datetime

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Strategy tag for imported positions
IMPORTED_STRATEGY_TAG = "IMPORTED"

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    logger.warning("python-dotenv not installed, skipping .env file")

def print_banner():
    """Print script banner"""
    print()
    print("=" * 80)
    print("IMPORT CURRENT POSITIONS TO TRACKER".center(80))
    print("=" * 80)
    print()
    print("This script will import all open positions to the position tracker.")
    print("Entry prices will be ESTIMATED at current market price.")
    print("P&L calculations will start from zero after import.")
    print()

def import_positions():
    """
    Import all current positions to position tracker
    
    Returns:
        Number of positions imported
    """
    try:
        from broker_manager import MultiBrokerManager, BrokerType, AccountType
        from position_tracker import PositionTracker
        
        print("🔄 Initializing broker connections...")
        print()
        
        # Initialize broker manager
        manager = MultiBrokerManager()
        
        # Initialize position tracker
        tracker = PositionTracker(storage_file="positions.json")
        
        # Track statistics
        total_imported = 0
        total_skipped = 0
        total_errors = 0
        
        # Get all active brokers
        brokers = manager.get_all_brokers()
        
        if not brokers:
            print("⚠️  No brokers configured - nothing to import")
            print()
            return 0
        
        print(f"📊 Found {len(brokers)} broker(s)")
        print()
        
        # Process each broker
        for broker in brokers:
            broker_name = broker.__class__.__name__
            print(f"📍 Processing {broker_name}...")
            
            try:
                # Get positions
                positions = broker.get_positions()
                
                if not positions:
                    print(f"   ℹ️  No positions found")
                    print()
                    continue
                
                print(f"   Found {len(positions)} position(s)")
                
                # Import each position
                for position in positions:
                    symbol = position.get('symbol')
                    if not symbol:
                        continue
                    
                    # Check if already tracked
                    existing = tracker.get_position(symbol)
                    if existing:
                        print(f"   ⏭️  {symbol}: Already tracked (entry: ${existing['entry_price']:.2f})")
                        total_skipped += 1
                        continue
                    
                    # Get current price as estimated entry price
                    quantity = position.get('quantity', 0)
                    current_price = broker.get_current_price(symbol)
                    
                    if not current_price or current_price == 0:
                        print(f"   ❌ {symbol}: Could not get current price")
                        total_errors += 1
                        continue
                    
                    # Calculate position size
                    size_usd = quantity * current_price
                    
                    # Track the position with estimated entry price
                    success = tracker.track_entry(
                        symbol=symbol,
                        entry_price=current_price,  # ESTIMATE: Use current price
                        quantity=quantity,
                        size_usd=size_usd,
                        strategy=IMPORTED_STRATEGY_TAG
                    )
                    
                    if success:
                        print(f"   ✅ {symbol}: Imported @ ${current_price:.2f} (${size_usd:.2f})")
                        total_imported += 1
                    else:
                        print(f"   ❌ {symbol}: Failed to import")
                        total_errors += 1
                
                print()
                
            except Exception as e:
                logger.error(f"Error processing {broker_name}: {e}", exc_info=True)
                total_errors += 1
                print()
        
        # Print summary
        print("-" * 80)
        print()
        print("📊 IMPORT SUMMARY")
        print()
        print(f"   ✅ Imported: {total_imported}")
        print(f"   ⏭️  Skipped (already tracked): {total_skipped}")
        print(f"   ❌ Errors: {total_errors}")
        print()
        
        if total_imported > 0:
            print("⚠️  IMPORTANT NOTES:")
            print()
            print("   1. Entry prices are ESTIMATED at current market price")
            print("   2. P&L calculations will start from ZERO")
            print("   3. Bot will use AGGRESSIVE exits for these positions")
            print("   4. These positions will exit on first sign of weakness")
            print()
            print("   This is safer than holding orphaned positions indefinitely.")
            print()
        
        return total_imported
        
    except ImportError as e:
        logger.error(f"Import error: {e}")
        logger.error("Make sure you're running from the repository root")
        return 0
    except Exception as e:
        logger.error(f"Error importing positions: {e}", exc_info=True)
        return 0

def main():
    """Main function"""
    print_banner()
    
    # Confirm with user
    print("⚠️  WARNING: This will estimate entry prices at current market price.")
    print("   P&L calculations will start from zero for imported positions.")
    print()
    
    try:
        response = input("Continue? (yes/no): ").strip().lower()
        if response not in ['yes', 'y']:
            print()
            print("❌ Import cancelled by user")
            print()
            return 1
    except (KeyboardInterrupt, EOFError):
        print()
        print("❌ Import cancelled by user")
        print()
        return 1
    
    print()
    
    # Import positions
    imported = import_positions()
    
    # Exit code
    if imported > 0:
        print("✅ Import complete")
        print()
        return 0
    else:
        print("ℹ️  No positions imported")
        print()
        return 0

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print()
        print("⚠️  Import interrupted by user")
        sys.exit(1)
    except Exception as e:
        print()
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)
