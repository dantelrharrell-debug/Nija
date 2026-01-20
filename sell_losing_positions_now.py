#!/usr/bin/env python3
"""
SELL ALL LOSING COINBASE POSITIONS NOW
======================================

Quick script to immediately sell all positions that are currently at a loss.
This is a more targeted version that only sells losing positions.

For FULL liquidation (all positions), use: emergency_sell_all_positions.py

Usage:
    python3 sell_losing_positions_now.py
"""

import sys
import logging
from pathlib import Path
from datetime import datetime

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
logger = logging.getLogger("sell_losing")


def main():
    """Sell all positions currently at a loss."""
    logger.error("=" * 80)
    logger.error("🚨 SELLING ALL LOSING POSITIONS NOW")
    logger.error("=" * 80)
    logger.error("")
    
    # Step 1: Connect to Coinbase
    logger.info("Connecting to Coinbase...")
    broker = CoinbaseBroker()
    
    if not broker.connect():
        logger.error("❌ Failed to connect to Coinbase!")
        return
    
    logger.info("✅ Connected to Coinbase")
    logger.info("")
    
    # Step 2: Get current positions
    logger.info("Fetching current positions...")
    positions = broker.get_positions()
    
    if not positions:
        logger.info("✅ No positions found - account clear!")
        return
    
    logger.info(f"Found {len(positions)} position(s)")
    logger.info("")
    
    # Step 3: Identify losing positions
    losing_positions = []
    profitable_positions = []
    
    for pos in positions:
        symbol = pos.get('symbol', 'UNKNOWN')
        quantity = pos.get('quantity', 0)
        current_price = pos.get('current_price', 0)
        entry_price = pos.get('entry_price', 0)
        value_usd = pos.get('value_usd', 0)
        
        if quantity == 0:
            continue
        
        # Calculate P&L if we have entry price
        if entry_price and entry_price > 0:
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
            
            if pnl_pct < 0:
                # Losing position
                # Note: Using abs() for quantity as defensive programming against
                # potential data corruption (Coinbase should never return negative)
                losing_positions.append({
                    'symbol': symbol,
                    'quantity': abs(quantity),
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'value': value_usd,
                    'pnl_pct': pnl_pct
                })
                logger.error(f"📉 LOSING: {symbol}")
                logger.error(f"     Entry: ${entry_price:.4f}")
                logger.error(f"     Current: ${current_price:.4f}")
                logger.error(f"     P&L: {pnl_pct:.2f}%")
                logger.error(f"     Value: ${value_usd:.2f}")
            else:
                # Profitable position
                profitable_positions.append({
                    'symbol': symbol,
                    'pnl_pct': pnl_pct
                })
                logger.info(f"📈 PROFITABLE: {symbol} at {pnl_pct:+.2f}% - KEEPING")
        else:
            # No entry price - can't determine if losing
            # Be conservative and sell it
            # Note: Using abs() for quantity as defensive programming
            losing_positions.append({
                'symbol': symbol,
                'quantity': abs(quantity),
                'entry_price': 0,
                'current_price': current_price,
                'value': value_usd,
                'pnl_pct': 0
            })
            logger.warning(f"⚠️  UNKNOWN P&L: {symbol} - NO ENTRY PRICE")
            logger.warning(f"     Current: ${current_price:.4f}")
            logger.warning(f"     Value: ${value_usd:.2f}")
            logger.warning(f"     Selling to be safe")
    
    logger.info("")
    logger.error(f"Summary: {len(losing_positions)} losing, {len(profitable_positions)} profitable")
    logger.info("")
    
    if not losing_positions:
        logger.info("🎉 No losing positions found!")
        logger.info("All positions are profitable or at breakeven.")
        return
    
    # Step 4: Force-sell all losing positions
    logger.error(f"Selling {len(losing_positions)} losing position(s)...")
    logger.error("")
    
    forced_stop_loss = ForcedStopLoss(broker)
    
    results = forced_stop_loss.force_sell_multiple_positions(
        positions=losing_positions,
        reason="NIJA IS FOR PROFIT NOT LOSSES - Immediate exit of losing positions"
    )
    
    # Step 5: Report results
    logger.error("")
    logger.error("=" * 80)
    logger.error("📊 RESULTS")
    logger.error("=" * 80)
    logger.error("")
    
    successful = 0
    failed = 0
    
    for symbol, (success, result, error) in results.items():
        if success:
            successful += 1
            logger.error(f"✅ {symbol}: SOLD")
        else:
            failed += 1
            logger.error(f"❌ {symbol}: FAILED - {error}")
    
    logger.error("")
    logger.error(f"Sold: {successful}/{len(losing_positions)}")
    logger.error(f"Failed: {failed}/{len(losing_positions)}")
    logger.error(f"Kept (profitable): {len(profitable_positions)}")
    logger.error("")
    
    if failed > 0:
        logger.error("⚠️  Some positions failed to sell!")
        logger.error("Check Coinbase UI: https://www.coinbase.com/advanced-trade/spot")
    else:
        logger.error("🎉 ALL LOSING POSITIONS SOLD!")
    
    logger.error("")
    logger.error("=" * 80)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.error("")
        logger.error("Interrupted by user (Ctrl+C)")
        logger.error("")
    except Exception as e:
        logger.error("")
        logger.error(f"❌ Exception: {e}")
        logger.error("")
        import traceback
        traceback.print_exc()
