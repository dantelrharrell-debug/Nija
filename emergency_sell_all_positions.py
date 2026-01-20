#!/usr/bin/env python3
"""
EMERGENCY LIQUIDATION SCRIPT
============================

Force-sell ALL Coinbase positions immediately to stop losses.

This script:
1. Connects to Coinbase broker
2. Fetches current positions from Coinbase API
3. Force-sells ALL positions using market orders
4. Reports status

Usage:
    python3 emergency_sell_all_positions.py

Safety:
- Uses ForcedStopLoss module for safe execution
- Logs all actions for audit trail
- Market orders for immediate execution
"""

import sys
import logging
from pathlib import Path

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent / "bot"))

from broker_manager import CoinbaseBroker
from forced_stop_loss import ForcedStopLoss

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("emergency_liquidation")


def main():
    """Emergency liquidation of all Coinbase positions."""
    logger.error("=" * 80)
    logger.error("🚨 EMERGENCY LIQUIDATION - FORCE SELL ALL POSITIONS")
    logger.error("=" * 80)
    logger.error("")
    logger.error("This script will IMMEDIATELY sell ALL positions on Coinbase.")
    logger.error("This action CANNOT be undone.")
    logger.error("")
    
    # Confirm user wants to proceed
    print("\n⚠️  WARNING: This will sell ALL positions immediately!")
    print("Are you sure you want to proceed? (type 'YES' to confirm): ", end="")
    confirmation = input().strip()
    
    if confirmation != "YES":
        logger.info("Emergency liquidation CANCELLED by user.")
        return
    
    logger.error("User confirmed - proceeding with emergency liquidation...")
    logger.error("")
    
    # Step 1: Connect to Coinbase
    logger.info("Step 1: Connecting to Coinbase broker...")
    broker = CoinbaseBroker()
    
    if not broker.connect():
        logger.error("❌ FAILED to connect to Coinbase!")
        logger.error("Cannot proceed with liquidation.")
        return
    
    logger.info("✅ Connected to Coinbase")
    logger.info("")
    
    # Step 2: Get current positions from Coinbase API
    logger.info("Step 2: Fetching current positions from Coinbase...")
    positions = broker.get_positions()
    
    if not positions:
        logger.info("✅ No positions found on Coinbase - account already clear!")
        return
    
    logger.error(f"⚠️  Found {len(positions)} position(s) to liquidate:")
    logger.error("")
    
    total_value = 0
    positions_to_sell = []
    
    for pos in positions:
        symbol = pos.get('symbol', 'UNKNOWN')
        quantity = pos.get('quantity', 0)
        current_price = pos.get('current_price', 0)
        value_usd = pos.get('value_usd', 0)
        
        logger.error(f"   {symbol}:")
        logger.error(f"      Quantity: {quantity:.8f}")
        logger.error(f"      Price: ${current_price:.4f}")
        logger.error(f"      Value: ${value_usd:.2f}")
        
        total_value += value_usd
        
        # Prepare for forced sell
        if quantity > 0:
            positions_to_sell.append({
                'symbol': symbol,
                'quantity': quantity,
                'value': value_usd
            })
    
    logger.error("")
    logger.error(f"   Total portfolio value: ${total_value:.2f}")
    logger.error("")
    
    if not positions_to_sell:
        logger.info("No valid positions to sell (all have zero quantity)")
        return
    
    # Step 3: Force-sell all positions
    logger.error("Step 3: Force-selling all positions (MARKET ORDERS)...")
    logger.error("")
    
    forced_stop_loss = ForcedStopLoss(broker)
    
    results = forced_stop_loss.force_sell_multiple_positions(
        positions=positions_to_sell,
        reason="EMERGENCY LIQUIDATION - User requested immediate exit of all positions"
    )
    
    # Step 4: Report results
    logger.error("")
    logger.error("=" * 80)
    logger.error("📊 EMERGENCY LIQUIDATION COMPLETE")
    logger.error("=" * 80)
    logger.error("")
    
    successful = 0
    failed = 0
    total_sold_value = 0
    
    for symbol, (success, result, error) in results.items():
        if success:
            successful += 1
            # Find original position to get value
            for pos in positions_to_sell:
                if pos['symbol'] == symbol:
                    total_sold_value += pos['value']
                    break
            logger.error(f"✅ {symbol}: SOLD")
        else:
            failed += 1
            logger.error(f"❌ {symbol}: FAILED - {error}")
    
    logger.error("")
    logger.error(f"Successful: {successful}/{len(positions_to_sell)}")
    logger.error(f"Failed: {failed}/{len(positions_to_sell)}")
    logger.error(f"Estimated value sold: ${total_sold_value:.2f}")
    logger.error("")
    
    if failed > 0:
        logger.error("⚠️  Some positions failed to sell!")
        logger.error("Check Coinbase Advanced Trade UI for remaining positions:")
        logger.error("https://www.coinbase.com/advanced-trade/spot")
    else:
        logger.error("🎉 ALL POSITIONS SUCCESSFULLY LIQUIDATED!")
    
    logger.error("")
    logger.error("=" * 80)
    
    # Step 5: Clean up stale position files
    logger.info("")
    logger.info("Step 5: Cleaning up stale position tracking files...")
    
    position_files = [
        Path("data/open_positions.json"),
        Path("positions.json"),
        Path("bot_positions.json")
    ]
    
    for pos_file in position_files:
        if pos_file.exists():
            backup = pos_file.with_suffix(f'.emergency_backup_{pos_file.stat().st_mtime:.0f}')
            try:
                pos_file.rename(backup)
                logger.info(f"✅ Backed up {pos_file} to {backup}")
            except Exception as e:
                logger.warning(f"⚠️  Could not backup {pos_file}: {e}")
    
    logger.info("")
    logger.info("✅ Emergency liquidation complete.")
    logger.info("")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.error("")
        logger.error("Emergency liquidation INTERRUPTED by user (Ctrl+C)")
        logger.error("")
    except Exception as e:
        logger.error("")
        logger.error(f"❌ EXCEPTION during emergency liquidation: {e}")
        logger.error("")
        import traceback
        traceback.print_exc()
