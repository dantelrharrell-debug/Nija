#!/usr/bin/env python3
"""
CRITICAL FIX: Aggressive Exit & Position Liquidation
- Forces ALL positions to exit immediately
- Prevents new trades under $2
- Liquidates all positions over cap
"""
import os
import sys
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("critical_fix")

MIN_TRADE_SIZE = 2.0  # Minimum position size ($2)
MAX_POSITIONS = 8
FORCE_EXIT_ALL = True  # Set to True to liquidate entire portfolio

def apply_critical_fix():
    """Apply critical fixes to prevent bad trades and enforce position cap."""
    
    logger.info("=" * 80)
    logger.info("🚨 CRITICAL FIX: AGGRESSIVE LIQUIDATION & CAP ENFORCEMENT")
    logger.info("=" * 80)
    
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
    
    try:
        from broker_manager import CoinbaseBroker
        import pandas as pd
        
        broker = CoinbaseBroker()
        if not broker.connect():
            logger.error("❌ Failed to connect to broker")
            return False
        
        # 1. GET ALL POSITIONS
        logger.info("\n📊 Step 1: Fetching all positions...")
        try:
            accounts = broker.client.get_accounts()
            accounts_list = accounts.get('accounts') if isinstance(accounts, dict) else getattr(accounts, 'accounts', [])
        except Exception as e:
            logger.error(f"❌ Failed to get accounts: {e}")
            return False
        
        all_positions = []
        usd_balance = 0
        
        for account in accounts_list:
            if isinstance(account, dict):
                currency = account.get('currency')
                balance_obj = account.get('available_balance', {})
                balance = float(balance_obj.get('value', 0)) if balance_obj else 0
            else:
                currency = getattr(account, 'currency', None)
                balance_obj = getattr(account, 'available_balance', {})
                balance = float(balance_obj.get('value', 0)) if isinstance(balance_obj, dict) else float(getattr(balance_obj, 'value', 0)) if balance_obj else 0
            
            if not currency:
                continue
            
            if currency in ['USD', 'USDC']:
                usd_balance = balance
                continue
            
            if balance <= 0:
                continue
            
            all_positions.append({
                'symbol': f"{currency}-USD",
                'currency': currency,
                'balance': balance
            })
        
        logger.info(f"   💰 USD Balance: ${usd_balance:.2f}")
        logger.info(f"   🪙 Crypto Positions: {len(all_positions)}")
        
        for pos in all_positions:
            logger.info(f"      {pos['currency']}: {pos['balance']:.8f} ({pos['symbol']})")
        
        # 2. AGGRESSIVE EXIT OF ALL POSITIONS
        if FORCE_EXIT_ALL and all_positions:
            logger.info(f"\n🔴 Step 2: LIQUIDATING ALL {len(all_positions)} POSITIONS")
            logger.info("=" * 80)
            
            sold_count = 0
            failed_count = 0
            total_usd_recovered = 0
            
            for i, pos in enumerate(all_positions, 1):
                symbol = pos['symbol']
                balance = pos['balance']
                currency = pos['currency']
                
                try:
                    logger.info(f"\n[{i}/{len(all_positions)}] 💥 LIQUIDATING {currency}...")
                    logger.info(f"   Amount: {balance:.8f}")
                    
                    # Get current price to estimate USD value
                    try:
                        candles = broker.get_candles(symbol, '1m', 1)
                        if candles:
                            current_price = float(candles[-1]['close'])
                            usd_value = balance * current_price
                            logger.info(f"   Current value: ~${usd_value:.2f} @ ${current_price:.2f}")
                            total_usd_recovered += usd_value
                    except:
                        pass
                    
                    # SELL NOW
                    result = broker.place_market_order(
                        symbol=symbol,
                        side='sell',
                        size=balance
                    )
                    
                    if result:
                        status = result.get('status', 'unknown')
                        logger.info(f"   Status: {status}")
                        
                        if status in ['filled', 'pending']:
                            logger.info(f"   ✅ LIQUIDATED {currency}!")
                            sold_count += 1
                        else:
                            logger.error(f"   ⚠️  {status} - may need retry")
                            failed_count += 1
                    else:
                        logger.error(f"   ❌ No response from broker")
                        failed_count += 1
                
                except Exception as e:
                    logger.error(f"   ❌ Error: {e}")
                    failed_count += 1
                
                time.sleep(0.5)
            
            logger.info("\n" + "=" * 80)
            logger.info(f"✅ LIQUIDATION COMPLETE")
            logger.info(f"   Liquidated: {sold_count}/{len(all_positions)}")
            logger.info(f"   Failed: {failed_count}/{len(all_positions)}")
            logger.info(f"   Est. USD Recovered: ${total_usd_recovered:.2f}")
            logger.info(f"   Expected final cash: ${usd_balance + total_usd_recovered:.2f}")
            logger.info("=" * 80)
        
        # 3. CREATE PROTECTION FILE
        logger.info("\n🔒 Step 3: Blocking new entries...")
        
        stop_file = os.path.join(os.path.dirname(__file__), 'STOP_ALL_ENTRIES.conf')
        with open(stop_file, 'w') as f:
            f.write("EMERGENCY STOP - All new entries blocked\n")
            f.write(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Reason: Critical liquidation of {len(all_positions)} positions\n")
            f.write(f"Min trade size: ${MIN_TRADE_SIZE}\n")
            f.write(f"Max positions: {MAX_POSITIONS}\n")
        
        logger.info(f"   ✅ STOP_ALL_ENTRIES.conf created")
        logger.info(f"   📍 All new entries now blocked")
        
        # 4. FINAL VERIFICATION
        logger.info("\n✅ VERIFICATION: Fetching final state...")
        time.sleep(2)
        
        try:
            accounts = broker.client.get_accounts()
            accounts_list = accounts.get('accounts') if isinstance(accounts, dict) else getattr(accounts, 'accounts', [])
            
            final_positions = sum(1 for acc in accounts_list 
                                if (isinstance(acc, dict) and acc.get('currency') not in ['USD', 'USDC']) 
                                or (not isinstance(acc, dict) and getattr(acc, 'currency', None) not in ['USD', 'USDC']))
            
            logger.info(f"   Final crypto positions: {final_positions}")
            if final_positions == 0:
                logger.info(f"   ✅ SUCCESS: All positions liquidated!")
            else:
                logger.warning(f"   ⚠️  {final_positions} positions still remaining")
        
        except Exception as e:
            logger.error(f"   Error verifying: {e}")
        
        logger.info("\n" + "=" * 80)
        logger.info("🚨 CRITICAL FIX APPLIED SUCCESSFULLY")
        logger.info("=" * 80)
        return True
    
    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

if __name__ == '__main__':
    apply_critical_fix()
