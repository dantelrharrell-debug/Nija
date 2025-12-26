#!/usr/bin/env python3
"""
EMERGENCY LIQUIDATION - Sell ALL positions immediately
This overrides all trading logic and liquidates the entire portfolio
"""
import os
import sys
import time
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("liquidate_all")

def liquidate_all():
    """Sell ALL crypto positions immediately - no exceptions."""
    
    logger.info("=" * 80)
    logger.info("🚨 EMERGENCY LIQUIDATION - SELLING ALL POSITIONS")
    logger.info("=" * 80)
    
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
    
    try:
        from broker_manager import CoinbaseBroker
        
        broker = CoinbaseBroker()
        if not broker.connect():
            logger.error("❌ Failed to connect to broker")
            return False
        
        # Get ALL positions
        logger.info("\n📊 Fetching all positions...")
        try:
            accounts = broker.client.get_accounts()
            accounts_list = accounts.get('accounts') if isinstance(accounts, dict) else getattr(accounts, 'accounts', [])
        except Exception as e:
            logger.error(f"❌ Failed to get accounts: {e}")
            return False
        
        positions_to_sell = []
        
        for account in accounts_list:
            if isinstance(account, dict):
                currency = account.get('currency')
                balance_obj = account.get('available_balance', {})
                balance = float(balance_obj.get('value', 0)) if balance_obj else 0
            else:
                currency = getattr(account, 'currency', None)
                balance_obj = getattr(account, 'available_balance', {})
                balance = float(balance_obj.get('value', 0)) if isinstance(balance_obj, dict) else float(getattr(balance_obj, 'value', 0)) if balance_obj else 0
            
            if not currency or balance <= 0 or currency in ['USD', 'USDC']:
                continue
            
            symbol = f"{currency}-USD"
            positions_to_sell.append({
                'symbol': symbol,
                'currency': currency,
                'balance': balance
            })
        
        total_positions = len(positions_to_sell)
        logger.info(f"\n🔴 Found {total_positions} positions to liquidate")
        
        if total_positions == 0:
            logger.info("✅ No crypto positions to sell")
            return True
        
        # List all positions
        for i, pos in enumerate(positions_to_sell, 1):
            logger.info(f"  {i}. {pos['currency']}: {pos['balance']:.8f}")
        
        # Sell ALL positions concurrently
        logger.info(f"\n🔴 SELLING ALL {total_positions} POSITIONS NOW...")
        logger.info("=" * 80)
        
        sold_count = 0
        failed_count = 0
        
        for i, position in enumerate(positions_to_sell, 1):
            symbol = position['symbol']
            balance = position['balance']
            currency = position['currency']
            
            try:
                logger.info(f"[{i}/{total_positions}] Selling {currency}...")
                
                result = broker.place_market_order(
                    symbol=symbol,
                    side='sell',
                    size=balance
                )
                
                if result and result.get('status') == 'filled':
                    logger.info(f"  ✅ SOLD {currency}!")
                    sold_count += 1
                else:
                    logger.error(f"  ❌ Sale pending/failed for {currency}")
                    failed_count += 1
            
            except Exception as e:
                logger.error(f"  ❌ Error selling {currency}: {e}")
                failed_count += 1
            
            # Rate limiting
            time.sleep(0.5)
        
        logger.info("\n" + "=" * 80)
        logger.info(f"✅ LIQUIDATION COMPLETE")
        logger.info(f"   Sold: {sold_count}/{total_positions}")
        logger.info(f"   Failed: {failed_count}/{total_positions}")
        logger.info("=" * 80)
        
        return sold_count == total_positions
    
    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == '__main__':
    success = liquidate_all()
    sys.exit(0 if success else 1)
