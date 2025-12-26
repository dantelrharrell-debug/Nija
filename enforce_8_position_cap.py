#!/usr/bin/env python3
"""
AGGRESSIVE POSITION ENFORCER - Strictly limit to 8 positions max
Liquidates ALL excess positions immediately
"""
import os
import sys
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("enforce_cap_aggressive")

MAX_POSITIONS = 8

def enforce_position_cap():
    """Aggressively enforce 8-position maximum by selling excess immediately."""
    
    logger.info("=" * 80)
    logger.info("🔒 AGGRESSIVE POSITION CAP ENFORCER (MAX: 8)")
    logger.info("=" * 80)
    
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
    
    try:
        from broker_manager import CoinbaseBroker
        
        broker = CoinbaseBroker()
        if not broker.connect():
            logger.error("❌ Failed to connect to broker")
            return False
        
        # Get all positions
        logger.info("\n📊 Fetching all positions...")
        try:
            accounts = broker.client.get_accounts()
            accounts_list = accounts.get('accounts') if isinstance(accounts, dict) else getattr(accounts, 'accounts', [])
        except Exception as e:
            logger.error(f"❌ Failed to get accounts: {e}")
            return False
        
        # Calculate position values and count
        positions = []
        
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
            
            positions.append({
                'symbol': f"{currency}-USD",
                'currency': currency,
                'balance': balance
            })
        
        current_count = len(positions)
        logger.info(f"📊 Current positions: {current_count}")
        
        if current_count <= MAX_POSITIONS:
            logger.info(f"✅ Position count ({current_count}) is within limit ({MAX_POSITIONS})")
            return True
        
        # EXCESS DETECTED - Must liquidate
        excess_count = current_count - MAX_POSITIONS
        logger.warning(f"\n⚠️  EXCESS POSITIONS DETECTED!")
        logger.warning(f"   Current: {current_count}, Max: {MAX_POSITIONS}, Excess: {excess_count}")
        logger.warning(f"\n🚨 LIQUIDATING {excess_count} POSITIONS NOW!")
        
        # Sort by balance (smallest first) to minimize impact
        positions.sort(key=lambda x: x['balance'])
        
        # Keep only the top MAX_POSITIONS (largest balance)
        positions_to_sell = positions[:excess_count]
        
        logger.info(f"\n🔴 Positions to liquidate ({excess_count}):")
        for i, pos in enumerate(positions_to_sell, 1):
            logger.info(f"   {i}. {pos['currency']}: {pos['balance']:.8f}")
        
        sold_count = 0
        failed_count = 0
        
        for i, position in enumerate(positions_to_sell, 1):
            symbol = position['symbol']
            balance = position['balance']
            currency = position['currency']
            
            try:
                logger.info(f"\n[{i}/{excess_count}] Liquidating {currency}...")
                
                result = broker.place_market_order(
                    symbol=symbol,
                    side='sell',
                    quantity=balance,
                    size_type='base'
                )
                
                if result and result.get('status') == 'filled':
                    logger.info(f"  ✅ LIQUIDATED {currency}")
                    sold_count += 1
                else:
                    logger.error(f"  ⚠️  Status: {result.get('status') if result else 'No result'}")
                    failed_count += 1
            
            except Exception as e:
                logger.error(f"  ❌ Error: {e}")
                failed_count += 1
            
            time.sleep(0.5)
        
        logger.info("\n" + "=" * 80)
        logger.info(f"✅ ENFORCER COMPLETE")
        logger.info(f"   Liquidated: {sold_count}/{excess_count}")
        logger.info(f"   Failed: {failed_count}/{excess_count}")
        logger.info(f"   Expected positions after: {MAX_POSITIONS}")
        logger.info("=" * 80)
        
        return True
    
    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == '__main__':
    enforce_position_cap()
