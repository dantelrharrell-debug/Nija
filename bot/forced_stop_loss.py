"""
NIJA Forced Stop-Loss Execution
================================

FIX #2: STOP-LOSS MUST SELL BY POSITION SIZE — NOT CASH

CRITICAL RULES:
- sell_quantity = full_position_quantity
- FORCE MARKET SELL
- IGNORE MIN SIZE
- IGNORE PROFIT TARGETS
- If stop-loss fires:
  * No sizing logic
  * No filters
  * No confidence checks
  * No "position too small"
  * SELL EVERYTHING

This is non-negotiable.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.stop_loss")


class ForcedStopLoss:
    """
    Forced stop-loss execution that bypasses all filters and constraints.
    
    When a stop-loss is triggered, this module ensures the position is
    sold IMMEDIATELY at market price, regardless of:
    - Minimum order size
    - Profit targets
    - Market filters
    - Confidence scores
    - Position size constraints
    
    The ONLY goal is to exit the position to limit losses.
    """
    
    def __init__(self, broker):
        """
        Initialize forced stop-loss executor.
        
        Args:
            broker: Broker instance to execute orders
        """
        self.broker = broker
        self.stop_loss_executions = []  # Track all forced executions
        logger.info("ForcedStopLoss initialized - ready to enforce stop-losses")
    
    def check_stop_loss_triggered(
        self, 
        symbol: str,
        entry_price: float,
        current_price: float,
        stop_loss_pct: float
    ) -> bool:
        """
        Check if stop-loss is triggered for a position.
        
        Args:
            symbol: Trading pair symbol
            entry_price: Entry price of the position
            current_price: Current market price
            stop_loss_pct: Stop-loss percentage (negative, e.g., -0.01 for -1%)
            
        Returns:
            bool: True if stop-loss is triggered
        """
        if entry_price <= 0 or current_price <= 0:
            logger.warning(f"Invalid prices for {symbol}: entry=${entry_price}, current=${current_price}")
            return False
        
        # Calculate current P&L percentage
        pnl_pct = ((current_price - entry_price) / entry_price)
        
        # Stop-loss is triggered if P&L is below threshold
        is_triggered = pnl_pct <= stop_loss_pct
        
        if is_triggered:
            logger.warning(
                f"🚨 STOP-LOSS TRIGGERED: {symbol} "
                f"P&L={pnl_pct*100:.2f}% <= {stop_loss_pct*100:.2f}% "
                f"(entry=${entry_price:.2f}, current=${current_price:.2f})"
            )
        
        return is_triggered
    
    def force_sell_position(
        self,
        symbol: str,
        quantity: float,
        reason: str = "Stop-loss triggered"
    ) -> Tuple[bool, Optional[Dict], str]:
        """
        Force sell a position at market price, bypassing ALL constraints.
        
        CRITICAL: This is a FORCED execution:
        - Uses full position quantity (not cash amount)
        - Market order (immediate execution)
        - Ignores minimum size constraints
        - Ignores profit targets
        - No filters applied
        - No confidence checks
        
        Args:
            symbol: Trading pair symbol
            quantity: Full position quantity to sell
            reason: Reason for the forced sell
            
        Returns:
            Tuple of (success, result_dict, error_message)
        """
        logger.error("=" * 80)
        logger.error(f"🚨 FORCED STOP-LOSS EXECUTION: {symbol}")
        logger.error(f"   Reason: {reason}")
        logger.error(f"   Quantity: {quantity:.8f}")
        logger.error(f"   Order Type: MARKET (force sell)")
        logger.error(f"   Constraints: ALL BYPASSED")
        logger.error("=" * 80)
        
        if not self.broker:
            error_msg = "No broker available for forced execution"
            logger.error(f"   ❌ FAILED: {error_msg}")
            return False, None, error_msg
        
        if quantity <= 0:
            error_msg = f"Invalid quantity: {quantity}"
            logger.error(f"   ❌ FAILED: {error_msg}")
            return False, None, error_msg
        
        try:
            # Get current price for logging purposes
            try:
                current_price = self.broker.get_current_price(symbol)
                estimated_value = current_price * quantity if current_price else 0
                logger.error(f"   Current Price: ${current_price:.2f}")
                logger.error(f"   Estimated Value: ${estimated_value:.2f}")
            except Exception as price_err:
                logger.warning(f"   ⚠️ Could not get current price: {price_err}")
                current_price = None
            
            # FORCED MARKET SELL
            # Use 'base' size type to sell by quantity (not USD amount)
            logger.error(f"   🔴 EXECUTING FORCED MARKET SELL NOW...")
            
            result = self.broker.place_market_order(
                symbol=symbol,
                side='sell',
                quantity=quantity,
                size_type='base'  # Sell by base currency quantity
            )
            
            # Check result
            if result and result.get('status') not in ['error', 'unfilled']:
                logger.error(f"   ✅ FORCED SELL SUCCESSFUL")
                logger.error(f"   Order ID: {result.get('order_id', 'N/A')}")
                logger.error(f"   Status: {result.get('status', 'N/A')}")
                
                # Track this execution
                execution_record = {
                    'symbol': symbol,
                    'quantity': quantity,
                    'reason': reason,
                    'timestamp': time.time(),
                    'order_id': result.get('order_id'),
                    'estimated_value': current_price * quantity if current_price else 0
                }
                self.stop_loss_executions.append(execution_record)
                
                logger.error("=" * 80)
                return True, result, ""
            else:
                error_msg = result.get('error', result.get('message', 'Unknown error')) if result else 'No response from broker'
                logger.error(f"   ❌ FORCED SELL FAILED: {error_msg}")
                logger.error(f"   Full result: {result}")
                logger.error("=" * 80)
                return False, result, error_msg
                
        except Exception as e:
            error_msg = f"Exception during forced sell: {str(e)}"
            logger.error(f"   ❌ EXCEPTION: {error_msg}")
            logger.error(f"   Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            logger.error("=" * 80)
            return False, None, error_msg
    
    def force_sell_multiple_positions(
        self,
        positions: List[Dict],
        reason: str = "Batch stop-loss"
    ) -> Dict[str, Tuple[bool, Optional[Dict], str]]:
        """
        Force sell multiple positions (batch stop-loss execution).
        
        Args:
            positions: List of position dicts with 'symbol' and 'quantity'
            reason: Reason for the batch forced sell
            
        Returns:
            Dict mapping symbol to (success, result, error_message)
        """
        logger.error("=" * 80)
        logger.error(f"🚨 BATCH FORCED STOP-LOSS: {len(positions)} positions")
        logger.error(f"   Reason: {reason}")
        logger.error("=" * 80)
        
        results = {}
        
        for i, position in enumerate(positions, 1):
            symbol = position.get('symbol')
            quantity = position.get('quantity', 0)
            
            if not symbol or quantity <= 0:
                logger.warning(f"[{i}/{len(positions)}] Skipping invalid position: {position}")
                results[symbol] = (False, None, "Invalid position data")
                continue
            
            logger.error(f"[{i}/{len(positions)}] Forcing sell: {symbol}")
            success, result, error = self.force_sell_position(
                symbol=symbol,
                quantity=quantity,
                reason=reason
            )
            
            results[symbol] = (success, result, error)
            
            # Small delay between forced sells to avoid overwhelming the broker
            if i < len(positions):
                time.sleep(0.5)
        
        # Summary
        successful = sum(1 for s, _, _ in results.values() if s)
        failed = len(results) - successful
        
        logger.error("=" * 80)
        logger.error(f"🚨 BATCH FORCED STOP-LOSS COMPLETE")
        logger.error(f"   Successful: {successful}/{len(positions)}")
        logger.error(f"   Failed: {failed}/{len(positions)}")
        logger.error("=" * 80)
        
        return results
    
    def get_execution_history(self) -> List[Dict]:
        """Get history of all forced stop-loss executions."""
        return self.stop_loss_executions.copy()
    
    def clear_execution_history(self):
        """Clear execution history (for testing/reset)."""
        self.stop_loss_executions.clear()
        logger.info("Forced stop-loss execution history cleared")


def create_forced_stop_loss(broker) -> ForcedStopLoss:
    """
    Factory function to create a ForcedStopLoss instance.
    
    Args:
        broker: Broker instance
        
    Returns:
        ForcedStopLoss instance
    """
    return ForcedStopLoss(broker)
