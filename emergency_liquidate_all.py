#!/usr/bin/env python3
"""
EMERGENCY LIQUIDATION SCRIPT
Sells ALL cryptocurrency positions immediately, bypassing normal bot logic
Use this to stop bleeding when automated selling fails
"""

import os
import sys
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from dotenv import load_dotenv
load_dotenv()

from broker_manager import CoinbaseBroker
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("nija.emergency")

def main():
    print("=" * 80)
    print("🚨 EMERGENCY LIQUIDATION - SELL ALL POSITIONS")
    print("=" * 80)
    print("")
    print("⚠️  WARNING: This will sell ALL cryptocurrency positions immediately!")
    print("⚠️  This action cannot be undone!")
    print("")
    
    # Safety confirmation
    confirm = input("Type 'LIQUIDATE' to proceed: ")
    if confirm != 'LIQUIDATE':
        print("❌ Cancelled by user")
        return 1
    
    print("")
    logger.info("🔌 Connecting to Coinbase...")
    
    # Connect to broker
    broker = CoinbaseBroker()
    if not broker.connect():
        logger.error("❌ Failed to connect to Coinbase!")
        return 1
    
    logger.info("✅ Connected")
    logger.info("")
    
    # Get current positions
    logger.info("📊 Fetching current positions...")
    positions = broker.get_positions()
    
    if not positions:
        logger.info("✅ No positions found - portfolio is already clear!")
        return 0
    
    logger.info(f"Found {len(positions)} positions to liquidate:")
    logger.info("")
    
    total_value = 0
    for i, pos in enumerate(positions, 1):
        symbol = pos['symbol']
        quantity = pos['quantity']
        currency = pos['currency']
        
        try:
            price = broker.get_current_price(symbol)
            usd_value = quantity * price
            total_value += usd_value
            logger.info(f"  {i}. {currency:>6}: {quantity:>15.8f} @ ${price:>10.2f} = ${usd_value:>8.2f}")
        except Exception as e:
            logger.warning(f"  {i}. {currency:>6}: {quantity:>15.8f} (price unavailable)")
    
    logger.info("-" * 80)
    logger.info(f"Total Portfolio Value: ~${total_value:.2f}")
    logger.info("")
    
    # Final confirmation
    print("=" * 80)
    print(f"⚠️  FINAL CONFIRMATION: About to sell {len(positions)} positions worth ~${total_value:.2f}")
    print("=" * 80)
    confirm2 = input("Type 'YES' to proceed with liquidation: ")
    if confirm2 != 'YES':
        print("❌ Cancelled by user")
        return 1
    
    print("")
    logger.info("🔴 STARTING LIQUIDATION...")
    logger.info("=" * 80)
    
    successful_sells = 0
    failed_sells = 0
    
    for i, pos in enumerate(positions, 1):
        symbol = pos['symbol']
        quantity = pos['quantity']
        currency = pos['currency']
        
        logger.info(f"[{i}/{len(positions)}] Selling {symbol}...")
        
        try:
            # Attempt to sell
            result = broker.place_market_order(
                symbol=symbol,
                side='sell',
                quantity=quantity,
                size_type='base'
            )
            
            if result:
                status = result.get('status', 'unknown')
                error = result.get('error', None)
                
                if status == 'filled':
                    logger.info(f"  ✅ SOLD {currency} successfully!")
                    successful_sells += 1
                elif status in ['error', 'unfilled']:
                    logger.error(f"  ❌ FAILED to sell {currency}: {error}")
                    failed_sells += 1
                    
                    # Log details for manual intervention
                    logger.error(f"     Quantity: {quantity}")
                    logger.error(f"     Error: {error}")
                    logger.error(f"     Message: {result.get('message', 'N/A')}")
                else:
                    logger.warning(f"  ⚠️  {currency} status: {status}")
                    failed_sells += 1
            else:
                logger.error(f"  ❌ No response from broker for {currency}")
                failed_sells += 1
        
        except Exception as e:
            logger.error(f"  ❌ Exception selling {currency}: {e}")
            failed_sells += 1
        
        # Rate limiting - wait 1 second between sells
        if i < len(positions):
            time.sleep(1)
    
    logger.info("=" * 80)
    logger.info("LIQUIDATION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"✅ Successful: {successful_sells}/{len(positions)}")
    logger.info(f"❌ Failed: {failed_sells}/{len(positions)}")
    
    if failed_sells > 0:
        logger.warning("")
        logger.warning("⚠️  Some positions failed to sell!")
        logger.warning("⚠️  These may need manual intervention on Coinbase.com")
        logger.warning("⚠️  Check the logs above for specific error messages")
    
    # Check final balance
    logger.info("")
    logger.info("📊 Checking final balance...")
    try:
        balance_data = broker.get_account_balance()
        trading_balance = balance_data.get('trading_balance', 0.0)
        logger.info(f"Final trading balance: ${trading_balance:.2f}")
        
        # Check remaining positions
        remaining = broker.get_positions()
        if remaining:
            logger.warning(f"⚠️  {len(remaining)} positions still remain:")
            for pos in remaining:
                logger.warning(f"  • {pos['currency']}: {pos['quantity']}")
        else:
            logger.info("✅ Portfolio is now clear - all positions sold!")
    except Exception as e:
        logger.error(f"Error checking final balance: {e}")
    
    return 0 if failed_sells == 0 else 2

if __name__ == '__main__':
    sys.exit(main())
