#!/usr/bin/env python3
"""
Emergency script to sell all losing positions
Closes only positions with negative P&L
"""
import os
import sys
sys.path.insert(0, 'bot')

from broker_manager import CoinbaseBroker
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("=" * 70)
    logger.info("🔴 SELLING ALL LOSING POSITIONS")
    logger.info("=" * 70)
    
    # Initialize broker
    broker = CoinbaseBroker()
    
    # Get current holdings
    balance = broker.get_account_balance()
    crypto_holdings = balance.get('crypto', {})
    
    if not crypto_holdings:
        logger.info("✅ No crypto holdings found - portfolio is clean")
        return
    
    logger.info(f"📊 Found {len(crypto_holdings)} crypto holdings")
    logger.info("")
    
    losing_positions = []
    winning_positions = []
    
    # Analyze each position
    for currency, usd_value in crypto_holdings.items():
        if usd_value < 0.50:  # Skip dust
            logger.info(f"⏭️  {currency}: Too small (${usd_value:.2f}), skipping")
            continue
        
        symbol = f"{currency}-USD"
        
        try:
            # Get current price
            candles = broker.get_candles(symbol, '5m', 10)
            if not candles:
                logger.warning(f"⚠️  {currency}: Cannot get price, skipping")
                continue
            
            current_price = float(candles[-1].get('close', 0))
            if current_price <= 0:
                logger.warning(f"⚠️  {currency}: Invalid price, skipping")
                continue
            
            # Calculate quantity
            quantity = usd_value / current_price
            
            # Try to get historical entry price from position file
            # If not available, assume current value and mark as unknown
            position_info = {
                'currency': currency,
                'symbol': symbol,
                'quantity': quantity,
                'current_price': current_price,
                'usd_value': usd_value,
                'pnl_pct': 0,  # Unknown without entry price
                'entry_known': False
            }
            
            # Load saved positions to get entry prices
            try:
                import json
                with open('data/open_positions.json', 'r') as f:
                    saved_positions = json.load(f)
                    positions = saved_positions.get('positions', {})
                    
                    if symbol in positions:
                        entry_price = positions[symbol].get('entry_price', current_price)
                        pnl_pct = ((current_price - entry_price) / entry_price) * 100
                        position_info['pnl_pct'] = pnl_pct
                        position_info['entry_price'] = entry_price
                        position_info['entry_known'] = True
                        
                        logger.info(f"{'🔴' if pnl_pct < 0 else '🟢'} {currency}: ${usd_value:.2f} @ ${current_price:.4f} | P&L: {pnl_pct:+.2f}%")
                        
                        if pnl_pct < 0:
                            losing_positions.append(position_info)
                        else:
                            winning_positions.append(position_info)
                    else:
                        logger.info(f"⚪ {currency}: ${usd_value:.2f} @ ${current_price:.4f} | P&L: Unknown (not tracked)")
            except Exception as e:
                logger.info(f"⚪ {currency}: ${usd_value:.2f} @ ${current_price:.4f} | P&L: Unknown ({e})")
        
        except Exception as e:
            logger.error(f"❌ Error analyzing {currency}: {e}")
    
    logger.info("")
    logger.info("=" * 70)
    logger.info(f"📊 SUMMARY: {len(losing_positions)} losing, {len(winning_positions)} winning")
    logger.info("=" * 70)
    
    if not losing_positions:
        logger.info("✅ No losing positions to close!")
        return
    
    # Confirm before selling
    logger.info("")
    logger.info("🔴 WILL SELL THE FOLLOWING LOSING POSITIONS:")
    total_loss_usd = 0
    for pos in losing_positions:
        logger.info(f"   • {pos['currency']}: ${pos['usd_value']:.2f} (P&L: {pos['pnl_pct']:+.2f}%)")
        loss_usd = pos['usd_value'] * (pos['pnl_pct'] / 100)
        total_loss_usd += loss_usd
    
    logger.info(f"   💰 Total realized loss: ${total_loss_usd:+.2f}")
    logger.info("")
    
    # Execute sells
    logger.info("🔄 Starting liquidation...")
    logger.info("")
    
    closed_count = 0
    failed_count = 0
    
    for pos in losing_positions:
        symbol = pos['symbol']
        currency = pos['currency']
        quantity = pos['quantity']
        
        try:
            logger.info(f"🔴 Selling {currency}: {quantity:.8f} @ market")
            
            result = broker.place_market_order(
                symbol=symbol,
                side='sell',
                quantity=quantity,
                size_type='base'
            )
            
            if result and result.get('status') in ['filled', 'partial']:
                closed_count += 1
                logger.info(f"   ✅ {currency} sold successfully (P&L: {pos['pnl_pct']:+.2f}%)")
            else:
                failed_count += 1
                error = result.get('error', 'Unknown error') if result else 'No response'
                logger.error(f"   ❌ {currency} sale failed: {error}")
        
        except Exception as e:
            failed_count += 1
            logger.error(f"   ❌ Error selling {currency}: {e}")
    
    logger.info("")
    logger.info("=" * 70)
    logger.info(f"✅ LIQUIDATION COMPLETE")
    logger.info(f"   Closed: {closed_count}/{len(losing_positions)}")
    if failed_count > 0:
        logger.info(f"   Failed: {failed_count}")
    logger.info(f"   💰 Total loss realized: ${total_loss_usd:+.2f}")
    logger.info("=" * 70)

if __name__ == "__main__":
    main()
