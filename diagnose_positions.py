#!/usr/bin/env python3
"""
Diagnostic Script: Check Current Positions and Sell Readiness
Identifies why positions aren't being sold
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from dotenv import load_dotenv
load_dotenv()

from broker_manager import CoinbaseBroker
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("nija.diagnostic")

def main():
    logger.info("=" * 80)
    logger.info("POSITION DIAGNOSTIC - Analyzing Why Positions Aren't Selling")
    logger.info("=" * 80)
    
    # Connect to broker
    broker = CoinbaseBroker()
    if not broker.connect():
        logger.error("Failed to connect to Coinbase!")
        return 1
    
    # Get current positions
    logger.info("\n📊 CURRENT POSITIONS:")
    logger.info("-" * 80)
    positions = broker.get_positions()
    
    if not positions:
        logger.info("✅ No positions found - portfolio is clear!")
        return 0
    
    logger.info(f"Found {len(positions)} positions:")
    logger.info("")
    
    total_value = 0
    positions_under_1_dollar = []
    positions_over_1_dollar = []
    
    for i, pos in enumerate(positions, 1):
        symbol = pos['symbol']
        quantity = pos['quantity']
        currency = pos['currency']
        
        # Get current price
        try:
            price = broker.get_current_price(symbol)
            usd_value = quantity * price
            total_value += usd_value
            
            # Categorize
            if usd_value < 1.0:
                positions_under_1_dollar.append((symbol, quantity, usd_value))
                status = "🔴 SHOULD AUTO-SELL"
            else:
                positions_over_1_dollar.append((symbol, quantity, usd_value))
                status = "⚠️  Needs analysis"
            
            logger.info(f"{i}. {currency:>6} | qty: {quantity:>15.8f} | price: ${price:>10.2f} | value: ${usd_value:>8.2f} | {status}")
        except Exception as e:
            logger.error(f"{i}. {currency:>6} | ERROR getting price: {e}")
    
    logger.info("-" * 80)
    logger.info(f"Total Portfolio Value: ${total_value:.2f}")
    logger.info("")
    
    # Analysis
    logger.info("\n📋 ANALYSIS:")
    logger.info("=" * 80)
    logger.info(f"Positions under $1 (AUTO-EXIT criterion): {len(positions_under_1_dollar)}")
    logger.info(f"Positions over $1 (need market analysis): {len(positions_over_1_dollar)}")
    logger.info("")
    
    if positions_under_1_dollar:
        logger.info("🔴 POSITIONS THAT SHOULD BE AUTO-SOLD:")
        logger.info("-" * 80)
        for symbol, qty, value in positions_under_1_dollar:
            logger.info(f"  • {symbol}: ${value:.2f}")
        logger.info("")
        logger.info(f"⚠️  These {len(positions_under_1_dollar)} positions should have been automatically sold!")
        logger.info(f"⚠️  Total locked value: ${sum(v for _, _, v in positions_under_1_dollar):.2f}")
        logger.info("")
    
    # Test sell order for one small position
    if positions_under_1_dollar:
        logger.info("\n🧪 TESTING SELL ORDER (DRY RUN):")
        logger.info("=" * 80)
        test_symbol, test_qty, test_value = positions_under_1_dollar[0]
        logger.info(f"Test position: {test_symbol}")
        logger.info(f"Quantity: {test_qty}")
        logger.info(f"Value: ${test_value:.2f}")
        logger.info("")
        
        # Check if we can sell
        logger.info("Attempting to place sell order...")
        try:
            result = broker.place_market_order(
                symbol=test_symbol,
                side='sell',
                quantity=test_qty,
                size_type='base'
            )
            
            if result:
                status = result.get('status', 'unknown')
                error = result.get('error', None)
                message = result.get('message', None)
                
                logger.info(f"Result status: {status}")
                if error:
                    logger.error(f"ERROR: {error}")
                if message:
                    logger.info(f"Message: {message}")
                
                if status == 'filled':
                    logger.info(f"✅ SELL ORDER WOULD SUCCEED!")
                elif status in ['error', 'unfilled']:
                    logger.error(f"❌ SELL ORDER FAILED!")
                    logger.error(f"This is why positions aren't being sold!")
                    if error:
                        logger.error(f"Root cause: {error}")
            else:
                logger.error("❌ No response from broker.place_market_order()")
        except Exception as e:
            logger.error(f"❌ Exception during sell test: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("DIAGNOSTIC COMPLETE")
    logger.info("=" * 80)
    
    # Return count of problematic positions
    return len(positions_under_1_dollar)

if __name__ == '__main__':
    sys.exit(main())
