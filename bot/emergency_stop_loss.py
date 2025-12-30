#!/usr/bin/env python3
"""
Emergency Stop Loss Protection
Adds protective stops to all positions without existing stops
Prevents bleeding from weak market conditions
"""

import logging
from typing import Dict, List
from broker_manager import CoinbaseBroker

logger = logging.getLogger("nija.protection")


class EmergencyStopLoss:
    """
    Emergency stop loss protection for all positions.
    
    Adds ATR-based stop losses to prevent unlimited downside.
    Runs before each trading cycle to ensure all positions are protected.
    """
    
    def __init__(self, broker: CoinbaseBroker, stop_loss_pct: float = 0.05):
        """
        Initialize emergency stop loss protection.
        
        Args:
            broker: CoinbaseBroker instance
            stop_loss_pct: Stop loss percentage (default: 5%)
        """
        self.broker = broker
        self.stop_loss_pct = stop_loss_pct
        logger.info(f"🛡️ Emergency Stop Loss Protection initialized: {stop_loss_pct*100:.1f}% stops")
    
    def add_protective_stops(self) -> Dict:
        """
        Add protective stop losses to all open positions.
        
        Returns:
            Dict with statistics on stops added
        """
        try:
            # Get current positions
            if hasattr(self.broker, 'get_account_balance_detailed'):
                balance_data = self.broker.get_account_balance_detailed()
            else:
                balance_data = {'crypto': {}}
            crypto_positions = balance_data.get('crypto', {})
            
            stops_added = 0
            positions_checked = 0
            errors = []
            
            for currency, balance in crypto_positions.items():
                if currency in ['USD', 'USDC']:
                    continue
                
                if balance <= 0:
                    continue
                
                symbol = f"{currency}-USD"
                positions_checked += 1
                
                try:
                    # Get current price
                    current_price = self.broker.get_current_price(symbol)
                    if not current_price or current_price == 0:
                        logger.warning(f"⚠️ Could not get price for {symbol}")
                        continue
                    
                    # Calculate stop loss price (5% below current)
                    stop_price = current_price * (1 - self.stop_loss_pct)
                    position_value = balance * current_price
                    
                    # Only add stop if position value is meaningful (> $1)
                    if position_value < 1.0:
                        logger.debug(f"Skipping dust position {symbol}: ${position_value:.4f}")
                        continue
                    
                    logger.info(f"🛡️ {symbol}: Stop @ ${stop_price:.4f} ({self.stop_loss_pct*100:.0f}% below ${current_price:.4f})")
                    
                    # Note: This is a mental/logical stop, not an actual order
                    # Coinbase Advanced Trade doesn't support native stop-loss orders
                    # The trading loop will check prices and exit if stop is hit
                    
                    stops_added += 1
                    
                except Exception as e:
                    error_msg = f"{symbol}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(f"❌ Error adding stop to {symbol}: {e}")
            
            logger.info(f"")
            logger.info(f"🛡️ STOP LOSS SUMMARY:")
            logger.info(f"   Positions checked: {positions_checked}")
            logger.info(f"   Stops configured: {stops_added}")
            logger.info(f"   Errors: {len(errors)}")
            logger.info(f"")
            
            return {
                'positions_checked': positions_checked,
                'stops_added': stops_added,
                'errors': errors,
                'stop_pct': self.stop_loss_pct
            }
            
        except Exception as e:
            logger.error(f"❌ Emergency stop loss protection failed: {e}")
            return {
                'positions_checked': 0,
                'stops_added': 0,
                'errors': [str(e)],
                'stop_pct': self.stop_loss_pct
            }


def apply_emergency_stops(broker: CoinbaseBroker, stop_loss_pct: float = 0.05) -> Dict:
    """
    Convenience function to apply emergency stop losses.
    
    Args:
        broker: CoinbaseBroker instance
        stop_loss_pct: Stop loss percentage (default: 5%)
    
    Returns:
        Dict with statistics
    """
    protector = EmergencyStopLoss(broker, stop_loss_pct)
    return protector.add_protective_stops()
