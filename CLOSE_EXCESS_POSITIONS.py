#!/usr/bin/env python3
"""
EMERGENCY: Close excess positions to comply with 3-position limit.
Keeps APT-USD, FET-USD, VET-USD (top 3 performers).
Closes all other 10 positions.

RUN THIS ON RAILWAY:
    python3 CLOSE_EXCESS_POSITIONS.py

This will:
1. Close 10 positions via market sell orders
2. Update data/open_positions.json 
3. Get you down to 3 positions (compliant with RISK_LIMITS)
"""

import sys
import os
import json
from datetime import datetime, UTC

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot'))

from broker_manager import CoinbaseBroker
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("="*70)
    logger.info("🔥 EMERGENCY: CLOSING EXCESS POSITIONS TO COMPLY WITH 3-POSITION LIMIT")
    logger.info("="*70)
    
    # Load positions
    try:
        with open('data/open_positions.json', 'r') as f:
            data = json.load(f)
            positions = data.get('positions', {})
    except Exception as e:
        logger.error(f"❌ Failed to load positions: {e}")
        return False
    
    logger.info(f"📊 Loaded {len(positions)} positions\n")
    
    # Based on Railway logs (2025-12-24 21:28), keep top 3 performers:
    # APT-USD: +2.80%, FET-USD: +2.15%, VET-USD: +1.94%
    KEEP_SYMBOLS = ['APT-USD', 'FET-USD', 'VET-USD']
    
    # Close all others
    symbols_to_close = [s for s in positions.keys() if s not in KEEP_SYMBOLS]
    
    logger.info("="*70)
    logger.info(f"📌 KEEPING: {', '.join(KEEP_SYMBOLS)}")
    logger.info(f"🗑️  CLOSING: {len(symbols_to_close)} positions")
    logger.info("="*70)
    logger.info("")
    
    # Initialize broker
    try:
        broker = CoinbaseBroker()
        logger.info("✅ Broker connected\n")
    except Exception as e:
        logger.error(f"❌ Broker connection failed: {e}")
        return False
    
    closed_symbols = []
    failed_symbols = []
    
    for symbol in symbols_to_close:
        position = positions[symbol]
        crypto_quantity = position.get('crypto_quantity')
        direction = position.get('direction', 'BUY')
        
        # Determine sell/buy direction
        exit_side = 'sell' if direction == 'BUY' else 'buy'
        
        logger.info(f"🔄 Closing {symbol}...")
        logger.info(f"   {exit_side.upper()} {crypto_quantity:.8f} units")
        
        try:
            # Use EXACT same signature as trading_strategy.py
            order = broker.place_market_order(
                symbol,
                exit_side,
                crypto_quantity,
                size_type='base'  # Always 'base' when specifying crypto quantity
            )
            
            if order and order.get('status') == 'filled':
                fill_price = float(order.get('average_filled_price', 0))
                logger.info(f"   ✅ CLOSED @ ${fill_price:.4f}\n")
                closed_symbols.append(symbol)
            else:
                error = order.get('error', 'Unknown error') if order else 'No response'
                logger.error(f"   ❌ FAILED: {error}\n")
                failed_symbols.append(symbol)
        except Exception as e:
            logger.error(f"   ❌ Exception: {str(e)[:200]}\n")
            failed_symbols.append(symbol)
    
    # Update position tracker - remove successfully closed
    updated_positions = {s: p for s, p in positions.items() if s not in closed_symbols}
    
    # Save
    try:
        with open('data/open_positions.json', 'w') as f:
            json.dump({
                'positions': updated_positions,
                'last_updated': datetime.now(UTC).isoformat()
            }, f, indent=2)
        logger.info("💾 Position tracker updated\n")
    except Exception as e:
        logger.error(f"❌ Failed to save positions: {e}\n")
    
    # Summary
    logger.info("="*70)
    logger.info("📊 LIQUIDATION SUMMARY")
    logger.info("="*70)
    logger.info(f"  Started with: {len(positions)} positions")
    logger.info(f"  Successfully closed: {len(closed_symbols)} positions")
    logger.info(f"  Failed to close: {len(failed_symbols)} positions")
    logger.info(f"  Remaining: {len(updated_positions)} positions")
    logger.info(f"  Target: 3 positions")
    logger.info("="*70)
    
    if len(updated_positions) <= 3:
        logger.info("\n✅ SUCCESS: Position limit achieved!")
        logger.info(f"✅ Remaining positions: {', '.join(updated_positions.keys())}")
        logger.info("\n✅ NIJA is now compliant with 3-position limit!")
        logger.info("✅ Bot will continue managing these 3 positions automatically")
        return True
    else:
        logger.warning(f"\n⚠️  WARNING: Still have {len(updated_positions)} positions (target: 3)")
        if failed_symbols:
            logger.warning(f"   Failed to close: {', '.join(failed_symbols)}")
            logger.warning(f"   You may need to manually close these on Coinbase")
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
