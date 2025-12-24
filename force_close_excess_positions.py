#!/usr/bin/env python3
"""
Force close excess positions to comply with 3-position limit.
Keeps top 3 performers, closes remaining 9 positions.
"""

import sys
import os
import json
from datetime import datetime

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import BrokerManager
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def load_positions():
    """Load current positions from tracker"""
    positions_file = 'data/open_positions.json'
    try:
        with open(positions_file, 'r') as f:
            data = json.load(f)
            return data.get('positions', {})
    except Exception as e:
        logger.error(f"Failed to load positions: {e}")
        return {}

def save_positions(positions):
    """Save updated positions to tracker"""
    positions_file = 'data/open_positions.json'
    try:
        data = {
            'positions': positions,
            'last_updated': datetime.utcnow().isoformat()
        }
        with open(positions_file, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"💾 Saved {len(positions)} positions to tracker")
        return True
    except Exception as e:
        logger.error(f"Failed to save positions: {e}")
        return False

def get_current_price(broker, symbol):
    """Get current market price for symbol"""
    try:
        price = broker.get_current_price(symbol)
        if price and price > 0:
            return price
        logger.warning(f"Invalid price for {symbol}: {price}")
        return None
    except Exception as e:
        logger.error(f"Failed to get price for {symbol}: {e}")
        return None

def calculate_pnl(position, current_price):
    """Calculate P&L percentage for position"""
    try:
        entry_price = position.get('entry_price')
        direction = position.get('direction', 'BUY')
        
        if not entry_price or not current_price:
            return 0.0
        
        if direction == 'BUY':
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:  # SHORT
            pnl_pct = ((entry_price - current_price) / entry_price) * 100
        
        return pnl_pct
    except Exception as e:
        logger.error(f"Failed to calculate P&L: {e}")
        return 0.0

def close_position(broker, symbol, position):
    """Close a single position via market order"""
    try:
        direction = position.get('direction', 'BUY')
        crypto_quantity = position.get('crypto_quantity')
        
        if not crypto_quantity or crypto_quantity <= 0:
            logger.warning(f"⚠️  {symbol}: Invalid quantity {crypto_quantity}, skipping")
            return False
        
        # Determine sell/buy direction
        exit_signal = 'sell' if direction == 'BUY' else 'buy'
        
        logger.info(f"📤 Closing {symbol}: {exit_signal.upper()} {crypto_quantity:.8f} units")
        
        # Execute market order
        order = broker.place_market_order(
            symbol=symbol,
            side=exit_signal,
            size=crypto_quantity,
            size_type='base'
        )
        
        if order and order.get('status') == 'filled':
            fill_price = float(order.get('average_filled_price', 0))
            logger.info(f"✅ {symbol} CLOSED @ ${fill_price:.4f}")
            return True
        else:
            error_msg = order.get('error', 'Unknown error') if order else 'No order response'
            logger.error(f"❌ {symbol} close FAILED: {error_msg}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Exception closing {symbol}: {e}")
        return False

def main():
    """Main execution"""
    logger.info("="*80)
    logger.info("🔥 FORCE CLOSING EXCESS POSITIONS TO COMPLY WITH 3-POSITION LIMIT")
    logger.info("="*80)
    
    # Load positions
    positions = load_positions()
    if not positions:
        logger.error("❌ No positions found to close")
        return False
    
    logger.info(f"📊 Loaded {len(positions)} positions from tracker")
    
    # Initialize broker
    try:
        broker = BrokerManager()
        logger.info("✅ Broker connected")
    except Exception as e:
        logger.error(f"❌ Broker connection failed: {e}")
        return False
    
    # Calculate current P&L for all positions
    position_pnl = []
    for symbol, position in positions.items():
        current_price = get_current_price(broker, symbol)
        if current_price:
            pnl_pct = calculate_pnl(position, current_price)
            position_pnl.append({
                'symbol': symbol,
                'position': position,
                'current_price': current_price,
                'pnl_pct': pnl_pct
            })
            logger.info(f"   {symbol}: P&L {pnl_pct:+.2f}% @ ${current_price:.4f}")
        else:
            logger.warning(f"   {symbol}: Failed to get current price, assuming 0% P&L")
            position_pnl.append({
                'symbol': symbol,
                'position': position,
                'current_price': None,
                'pnl_pct': 0.0
            })
    
    # Sort by P&L (best to worst)
    position_pnl.sort(key=lambda x: x['pnl_pct'], reverse=True)
    
    # Keep top 3, close the rest
    keep_count = 3
    positions_to_keep = position_pnl[:keep_count]
    positions_to_close = position_pnl[keep_count:]
    
    logger.info("")
    logger.info("="*80)
    logger.info(f"📌 KEEPING TOP {keep_count} PERFORMERS:")
    logger.info("="*80)
    for item in positions_to_keep:
        logger.info(f"   ✅ {item['symbol']}: {item['pnl_pct']:+.2f}% - KEEPING")
    
    logger.info("")
    logger.info("="*80)
    logger.info(f"🗑️  CLOSING {len(positions_to_close)} POSITIONS:")
    logger.info("="*80)
    
    # Close excess positions
    closed_count = 0
    failed_count = 0
    updated_positions = {}
    
    for item in positions_to_close:
        symbol = item['symbol']
        position = item['position']
        pnl_pct = item['pnl_pct']
        
        logger.info(f"\n🔄 Closing {symbol} (P&L: {pnl_pct:+.2f}%)...")
        
        success = close_position(broker, symbol, position)
        if success:
            closed_count += 1
            logger.info(f"   ✅ {symbol} removed from tracker")
        else:
            failed_count += 1
            # Keep in tracker if close failed
            updated_positions[symbol] = position
            logger.warning(f"   ⚠️  {symbol} kept in tracker (close failed)")
    
    # Add kept positions to updated tracker
    for item in positions_to_keep:
        updated_positions[item['symbol']] = item['position']
    
    # Save updated positions
    logger.info("")
    logger.info("="*80)
    logger.info("💾 UPDATING POSITION TRACKER")
    logger.info("="*80)
    
    if save_positions(updated_positions):
        logger.info(f"✅ Position tracker updated: {len(updated_positions)} positions remaining")
    else:
        logger.error("❌ Failed to save position tracker")
    
    # Summary
    logger.info("")
    logger.info("="*80)
    logger.info("📊 LIQUIDATION SUMMARY")
    logger.info("="*80)
    logger.info(f"   Positions before: {len(positions)}")
    logger.info(f"   Target positions: {keep_count}")
    logger.info(f"   Successfully closed: {closed_count}")
    logger.info(f"   Failed to close: {failed_count}")
    logger.info(f"   Positions after: {len(updated_positions)}")
    logger.info("="*80)
    
    if len(updated_positions) <= keep_count:
        logger.info("✅ SUCCESS: Position limit compliance achieved!")
        return True
    else:
        logger.warning(f"⚠️  PARTIAL: Still have {len(updated_positions)} positions (target: {keep_count})")
        logger.warning(f"   {failed_count} positions failed to close and remain active")
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
