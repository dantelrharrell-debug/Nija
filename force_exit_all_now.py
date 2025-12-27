#!/usr/bin/env python3
"""
Force Exit All Positions - Emergency Stop Bleeding

This script immediately exits ALL positions at market prices to stop bleeding.
Use this as an emergency measure when the portfolio is losing significant value.

WARNING: This will:
- Sell ALL cryptocurrency positions immediately
- Use market orders (may have slippage)
- Not wait for profit targets
- Lock in current P&L (gains or losses)

Use this when:
- Portfolio is bleeding badly and you want to stop losses NOW
- You want to go to cash and reassess strategy
- Market conditions are extremely unfavorable

DO NOT USE if:
- You want to wait for profit targets
- Losses are small and manageable
- You believe positions will recover
"""

import os
import sys
import logging
import time

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
    """Force exit all positions immediately"""
    try:
        from broker_manager import CoinbaseBroker
        
        logger.info("=" * 80)
        logger.info("EMERGENCY: FORCE EXIT ALL POSITIONS")
        logger.info("=" * 80)
        
        # Confirm with user
        print("\n⚠️  WARNING: This will sell ALL positions at market prices RIGHT NOW!")
        print("This action cannot be undone.")
        print("\nCurrent losses will be locked in.")
        print("Any potential recoveries will be missed.")
        print("\nAre you ABSOLUTELY SURE you want to proceed?\n")
        
        response = input("Type 'EXIT ALL NOW' to confirm: ").strip()
        if response != "EXIT ALL NOW":
            logger.info("❌ Confirmation failed - aborting")
            logger.info("No positions were sold")
            return 0
        
        logger.info("\n✅ Confirmed - proceeding with emergency exit")
        
        # Initialize broker
        logger.info("\n1. Connecting to Coinbase...")
        broker = CoinbaseBroker()
        if not broker.connect():
            logger.error("❌ Failed to connect to Coinbase")
            return 1
        
        logger.info("✅ Connected to Coinbase")
        
        # Get current positions
        logger.info("\n2. Fetching positions...")
        positions = broker.get_positions()
        if not positions:
            logger.info("✅ No positions found - nothing to exit")
            return 0
        
        logger.info(f"⚠️  Found {len(positions)} positions to exit")
        
        # Calculate total portfolio value
        total_value = 0
        for pos in positions:
            try:
                symbol = pos.get('symbol')
                quantity = pos.get('quantity', 0)
                price = broker.get_current_price(symbol)
                if price and price > 0:
                    value = quantity * price
                    total_value += value
            except Exception:
                pass
        
        logger.info(f"💰 Total portfolio value: ~${total_value:.2f}")
        
        # Final confirmation
        print(f"\n⚠️  FINAL CONFIRMATION")
        print(f"About to sell {len(positions)} positions worth ~${total_value:.2f}")
        print(f"This will lock in all current gains/losses")
        print()
        
        response = input("Type 'CONFIRM' to proceed: ").strip()
        if response != "CONFIRM":
            logger.info("❌ Final confirmation failed - aborting")
            return 0
        
        # Exit all positions
        logger.info("\n3. Exiting positions...")
        logger.info("=" * 80)
        
        sold_count = 0
        skipped_count = 0
        error_count = 0
        total_sold_value = 0
        
        for i, pos in enumerate(positions, 1):
            symbol = pos.get('symbol', 'UNKNOWN')
            quantity = pos.get('quantity', 0)
            currency = pos.get('currency', symbol.split('-')[0] if '-' in symbol else symbol)
            
            logger.info(f"\n[{i}/{len(positions)}] {symbol}")
            logger.info("-" * 40)
            
            try:
                # Get current price
                price = broker.get_current_price(symbol)
                if not price or price == 0:
                    logger.warning("   ⚠️ Could not get price - skipping")
                    skipped_count += 1
                    continue
                
                value = quantity * price
                logger.info(f"   Quantity: {quantity:.8f} {currency}")
                logger.info(f"   Price: ${price:.2f}")
                logger.info(f"   Value: ${value:.2f}")
                
                # Skip dust (under $0.50)
                if value < 0.50:
                    logger.info("   ⏭️  Too small to sell - skipping")
                    skipped_count += 1
                    continue
                
                # Execute sell
                logger.info("   💰 SELLING NOW...")
                result = broker.place_market_order(
                    symbol=symbol,
                    side='sell',
                    quantity=quantity,
                    size_type='base'
                )
                
                if result and result.get('status') not in ['error', 'unfilled']:
                    logger.info("   ✅ SOLD")
                    sold_count += 1
                    total_sold_value += value
                else:
                    error_msg = result.get('error', 'Unknown') if result else 'No response'
                    logger.error(f"   ❌ Failed: {error_msg}")
                    error_count += 1
                
                # Rate limit protection
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"   ❌ Error: {e}")
                error_count += 1
        
        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("EXIT SUMMARY")
        logger.info("=" * 80)
        logger.info(f"\nTotal positions: {len(positions)}")
        logger.info(f"Successfully sold: {sold_count}")
        logger.info(f"Skipped (dust/no price): {skipped_count}")
        logger.info(f"Errors: {error_count}")
        logger.info(f"Total value sold: ~${total_sold_value:.2f}")
        
        if sold_count > 0:
            logger.info("\n✅ EMERGENCY EXIT COMPLETE")
            logger.info("All positions have been liquidated")
            logger.info("Portfolio is now in cash")
        else:
            logger.warning("\n⚠️  No positions were sold")
            logger.info("Check errors above for issues")
        
        logger.info("\n" + "=" * 80)
        
        # Next steps
        logger.info("\nNEXT STEPS:")
        logger.info("1. Review the exit prices and total value")
        logger.info("2. Check Coinbase to confirm all sells executed")
        logger.info("3. Decide if you want to:")
        logger.info("   a) Keep bot stopped and stay in cash")
        logger.info("   b) Restart bot with fresh positions")
        logger.info("   c) Modify strategy parameters")
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("\n❌ Interrupted by user - some positions may not have sold")
        return 1
    except Exception as e:
        logger.error(f"\n❌ Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
