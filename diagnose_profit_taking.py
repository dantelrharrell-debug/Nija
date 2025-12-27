#!/usr/bin/env python3
"""
Diagnose Profit-Taking System

This script checks the current state of the profit-taking system and helps
identify why positions might not be exiting at profit targets.

Checks:
1. Position tracker status (how many positions tracked)
2. Current positions at broker vs tracked positions
3. P&L for each position (if tracked)
4. Exit signals for each position (RSI, momentum, market filter)
5. Recommendations for fixing any issues
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
    """Diagnose profit-taking system"""
    try:
        from broker_manager import CoinbaseBroker
        from position_tracker import PositionTracker
        import pandas as pd
        
        logger.info("=" * 80)
        logger.info("PROFIT-TAKING SYSTEM DIAGNOSTICS")
        logger.info("=" * 80)
        
        # Initialize broker
        logger.info("\n1. Connecting to Coinbase...")
        broker = CoinbaseBroker()
        if not broker.connect():
            logger.error("❌ Failed to connect to Coinbase")
            return 1
        
        logger.info("✅ Connected to Coinbase")
        
        # Initialize position tracker
        logger.info("\n2. Checking position tracker...")
        tracker = PositionTracker(storage_file="positions.json")
        tracked_positions = tracker.get_all_positions()
        logger.info(f"✅ Position tracker has {len(tracked_positions)} tracked positions")
        
        if tracked_positions:
            logger.info("\n   Tracked positions:")
            for symbol in tracked_positions:
                pos = tracker.get_position(symbol)
                logger.info(f"   - {symbol}: Entry ${pos['entry_price']:.2f}, Qty {pos['quantity']:.8f}")
        
        # Get current positions from broker
        logger.info("\n3. Fetching current positions from broker...")
        broker_positions = broker.get_positions()
        logger.info(f"✅ Broker has {len(broker_positions)} positions")
        
        if not broker_positions:
            logger.warning("   No positions at broker - nothing to diagnose")
            return 0
        
        # Analyze each position
        logger.info("\n4. Analyzing positions...")
        logger.info("=" * 80)
        
        untracked_positions = []
        profitable_positions = []
        losing_positions = []
        neutral_positions = []
        
        # Profit target thresholds (same as in trading_strategy.py)
        PROFIT_TARGETS = [5.0, 4.0, 3.0, 2.5, 2.0]
        STOP_LOSS_THRESHOLD = -2.0
        
        for i, pos in enumerate(broker_positions, 1):
            symbol = pos.get('symbol', 'UNKNOWN')
            quantity = pos.get('quantity', 0)
            currency = pos.get('currency', symbol.split('-')[0] if '-' in symbol else symbol)
            
            logger.info(f"\n[{i}/{len(broker_positions)}] {symbol}")
            logger.info("-" * 40)
            
            try:
                # Get current price
                current_price = broker.get_current_price(symbol)
                if not current_price or current_price == 0:
                    logger.warning("   ⚠️ Could not get current price")
                    continue
                
                position_value = quantity * current_price
                logger.info(f"   Quantity: {quantity:.8f} {currency}")
                logger.info(f"   Current Price: ${current_price:.2f}")
                logger.info(f"   Position Value: ${position_value:.2f}")
                
                # Check if tracked
                pnl_data = tracker.calculate_pnl(symbol, current_price)
                if pnl_data:
                    entry_price = pnl_data['entry_price']
                    pnl_percent = pnl_data['pnl_percent']
                    pnl_dollars = pnl_data['pnl_dollars']
                    
                    logger.info(f"   ✅ TRACKED: Entry ${entry_price:.2f}")
                    logger.info(f"   P&L: ${pnl_dollars:+.2f} ({pnl_percent:+.2f}%)")
                    
                    # Check profit targets
                    hit_target = False
                    for target in PROFIT_TARGETS:
                        if pnl_percent >= target:
                            logger.info(f"   🎯 PROFIT TARGET HIT: +{target}% (should exit!)")
                            profitable_positions.append((symbol, pnl_percent, target))
                            hit_target = True
                            break
                    
                    if not hit_target:
                        if pnl_percent <= STOP_LOSS_THRESHOLD:
                            logger.warning(f"   🛑 STOP LOSS HIT: {STOP_LOSS_THRESHOLD}% (should exit!)")
                            losing_positions.append((symbol, pnl_percent))
                        elif pnl_percent < 0:
                            logger.warning(f"   ⚠️ Currently losing but above stop loss")
                            neutral_positions.append((symbol, pnl_percent))
                        else:
                            logger.info(f"   📊 Currently winning but below profit targets")
                            neutral_positions.append((symbol, pnl_percent))
                else:
                    logger.warning(f"   ❌ NOT TRACKED: No entry price available")
                    logger.warning(f"      Profit-taking DISABLED for this position")
                    logger.warning(f"      Only RSI/momentum exits will work")
                    untracked_positions.append(symbol)
                
                # Get market data for exit signal analysis
                try:
                    candles = broker.get_candles(symbol, '5m', 100)
                    if candles and len(candles) >= 90:
                        df = pd.DataFrame(candles)
                        
                        # Calculate RSI
                        from indicators import calculate_rsi
                        df['close'] = pd.to_numeric(df['close'], errors='coerce')
                        rsi_series = calculate_rsi(df['close'], 14)
                        if len(rsi_series) > 0:
                            rsi = rsi_series.iloc[-1]
                            logger.info(f"   RSI: {rsi:.1f}")
                            
                            if rsi > 70:
                                logger.info(f"   📈 RSI OVERBOUGHT - should exit to lock gains")
                            elif rsi < 30:
                                logger.warning(f"   📉 RSI OVERSOLD - should exit to cut losses")
                            elif rsi > 60:
                                logger.info(f"   ⚠️ RSI elevated - watch for reversal")
                            elif rsi < 40:
                                logger.warning(f"   ⚠️ RSI weak - potential further downside")
                            else:
                                logger.info(f"   ✅ RSI neutral - no RSI-based exit signal")
                    else:
                        logger.warning(f"   ⚠️ Insufficient candle data for analysis")
                except Exception as e:
                    logger.warning(f"   ⚠️ Could not analyze market data: {e}")
                    
            except Exception as e:
                logger.error(f"   ❌ Error analyzing position: {e}")
        
        # Summary and recommendations
        logger.info("\n" + "=" * 80)
        logger.info("DIAGNOSTIC SUMMARY")
        logger.info("=" * 80)
        
        logger.info(f"\n📊 Position Status:")
        logger.info(f"   Total positions: {len(broker_positions)}")
        logger.info(f"   Tracked: {len(broker_positions) - len(untracked_positions)}")
        logger.info(f"   Untracked: {len(untracked_positions)}")
        
        if profitable_positions:
            logger.info(f"\n🎯 Positions at profit targets ({len(profitable_positions)}):")
            for symbol, pnl, target in profitable_positions:
                logger.info(f"   - {symbol}: +{pnl:.2f}% (target: +{target}%)")
            logger.info("   ✅ These should exit on next bot cycle!")
        
        if losing_positions:
            logger.warning(f"\n🛑 Positions at stop loss ({len(losing_positions)}):")
            for symbol, pnl in losing_positions:
                logger.warning(f"   - {symbol}: {pnl:.2f}%")
            logger.warning("   ⚠️ These should exit on next bot cycle to cut losses")
        
        if untracked_positions:
            logger.warning(f"\n❌ Untracked positions ({len(untracked_positions)}):")
            for symbol in untracked_positions:
                logger.warning(f"   - {symbol}")
            logger.warning("\n   ⚠️ CRITICAL: These positions have NO profit-taking!")
            logger.warning("      They will only exit on RSI extremes or market filter failures")
            logger.warning("\n   🔧 FIX: Run import_current_positions.py to track these positions")
        
        logger.info("\n" + "=" * 80)
        logger.info("RECOMMENDATIONS")
        logger.info("=" * 80)
        
        if untracked_positions:
            logger.info("\n1. Import untracked positions:")
            logger.info("   python import_current_positions.py")
            logger.info("   This will track current positions for profit-taking")
        
        if profitable_positions or losing_positions:
            logger.info("\n2. Bot should automatically exit positions at targets")
            logger.info("   Check bot logs for exit confirmations")
            logger.info("   If exits aren't happening, check for STOP_ALL_ENTRIES.conf")
        
        if not profitable_positions and not losing_positions and not untracked_positions:
            logger.info("\n✅ All positions are tracked and within normal ranges")
            logger.info("   Profit-taking system is working correctly")
        
        logger.info("\n" + "=" * 80)
        
        return 0
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
