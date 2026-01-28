"""
NIJA Protective Stop-Loss Execution System
===========================================

MANDATORY SELL BY POSITION SIZE — NOT CASH

CRITICAL RULES:
- sell_quantity = full_position_quantity
- PROTECTIVE MARKET SELL (investor protection mode)
- IGNORE MIN SIZE (capital preservation takes priority)
- IGNORE PROFIT TARGETS (loss mitigation is the goal)
- If stop-loss fires:
  * No sizing logic
  * No filters
  * No confidence checks
  * No "position too small"
  * SELL EVERYTHING

PNL REPRESENTATION (NORMALIZED - Option A):
  pnl_pct = -0.12  # Fractional: -0.12 represents -12% loss
  stop_loss = -0.01  # Fractional: -0.01 represents -1% threshold
  
  if pnl_pct <= stop_loss:
      trigger_protective_exit()  # -12% <= -1%, SELL

INVESTOR MESSAGING:
  - This is a PROTECTIVE ACTION, not a system failure
  - Logs use WARNING severity (not ERROR)
  - Emphasizes capital preservation and risk management
  - "EMERGENCY EXIT MODE — SELL ONLY" replaces "ALL CONSTRAINTS BYPASSED"

This is non-negotiable capital protection.
"""

import logging
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.stop_loss")


class ForcedStopLoss:
    """
    Protective stop-loss execution system with capital preservation priority.
    
    When a stop-loss is triggered, this module ensures positions are
    sold IMMEDIATELY at market price, regardless of:
    - Minimum order size
    - Profit targets
    - Market filters
    - Confidence scores
    - Position size constraints
    
    The ONLY goal is capital preservation through risk mitigation.
    
    PNL FORMAT (FRACTIONAL):
    - Uses fractional format: -0.01 = -1%, -0.12 = -12%
    - Includes validation: assert abs(pnl_pct) < 1
    """
    
    def __init__(self, broker):
        """
        Initialize protective stop-loss executor.
        
        Args:
            broker: Broker instance to execute orders
        """
        self.broker = broker
        self.stop_loss_executions = []  # Track all protective executions
        logger.info("🛡️ Protective Stop-Loss System initialized - capital preservation active")
    
    def check_stop_loss_triggered(
        self, 
        symbol: str,
        entry_price: float,
        current_price: float,
        stop_loss_pct: float
    ) -> bool:
        """
        Check if stop-loss is triggered for a position.
        
        NORMALIZED FORMAT (Option A - Fractional):
        - pnl_pct is fractional: -0.12 represents -12%
        - stop_loss_pct is fractional: -0.01 represents -1%
        
        Args:
            symbol: Trading pair symbol
            entry_price: Entry price of the position
            current_price: Current market price
            stop_loss_pct: Stop-loss percentage (negative fractional, e.g., -0.01 for -1%)
            
        Returns:
            bool: True if stop-loss is triggered
        """
        if entry_price <= 0 or current_price <= 0:
            logger.warning(f"Invalid prices for {symbol}: entry=${entry_price}, current=${current_price}")
            return False
        
        # Calculate current P&L percentage (FRACTIONAL FORMAT: -0.01 = -1%)
        pnl_pct = ((current_price - entry_price) / entry_price)
        
        # CRITICAL: Validate PnL is in fractional format (not percentage)
        # If abs(pnl_pct) >= 1, it's likely a bug (percentage format being used incorrectly)
        assert abs(pnl_pct) < 1.0, f"PNL scale mismatch for {symbol}: {pnl_pct} (expected fractional format like -0.01 for -1%)"
        
        # Stop-loss is triggered if P&L is below threshold
        is_triggered = pnl_pct <= stop_loss_pct
        
        if is_triggered:
            logger.warning(
                f"🚨 PROTECTIVE STOP-LOSS TRIGGERED: {symbol} "
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
        Execute protective sell at market price with risk management override.
        
        CRITICAL: This is a PROTECTIVE execution for capital preservation:
        - Uses full position quantity (not cash amount)
        - Market order (immediate execution)
        - Ignores minimum size constraints
        - Ignores profit targets
        - No filters applied
        - No confidence checks
        
        CONCURRENCY FIXES (Issue #1):
        - FIX #4: Mandatory balance refresh before emergency sell
        - FIX #5: Proper orphan resolution (sync → rebuild → validate → sell)
        
        This is investor protection, not a system failure.
        
        Args:
            symbol: Trading pair symbol
            quantity: Full position quantity to sell
            reason: Reason for the protective sell
            
        Returns:
            Tuple of (success, result_dict, error_message)
        """
        logger.warning("=" * 80)
        logger.warning(f"🛡️ EMERGENCY EXIT MODE — SELL ONLY: {symbol}")
        logger.warning(f"   Reason: {reason}")
        logger.warning(f"   Quantity: {quantity:.8f}")
        logger.warning(f"   Order Type: MARKET (protective liquidation)")
        logger.warning(f"   Mode: PROTECTIVE ACTION — Risk Management Override")
        logger.warning("=" * 80)
        
        if not self.broker:
            error_msg = "No broker available for protective exit"
            logger.warning(f"   ❌ FAILED: {error_msg}")
            return False, None, error_msg
        
        if quantity <= 0:
            error_msg = f"Invalid quantity: {quantity}"
            logger.warning(f"   ❌ FAILED: {error_msg}")
            return False, None, error_msg
        
        try:
            # FIX #4: Mandatory Balance Refresh Before Emergency Sell
            # Even in protective mode, we MUST sync balances to validate available assets
            logger.warning(f"   🔄 FIX #4: Refreshing balances before emergency sell...")
            try:
                # Refresh account balance to get current state
                if hasattr(self.broker, 'get_account_balance'):
                    current_balance = self.broker.get_account_balance()
                    logger.warning(f"   Current USD balance: ${current_balance:.2f}")
                
                # FIX #5: Proper Orphan Resolution Logic
                # For orphan positions, we need to: sync balances → rebuild position → validate size → THEN sell
                # Get actual available asset quantity from broker
                available_asset = 0.0
                if hasattr(self.broker, 'get_positions'):
                    positions = self.broker.get_positions()
                    for pos in positions:
                        if pos.get('symbol') == symbol:
                            available_asset = float(pos.get('quantity', 0))
                            logger.warning(f"   Broker reports {available_asset:.8f} {symbol} available")
                            break
                
                # Validate that we have enough asset to sell
                if available_asset > 0 and available_asset < quantity:
                    logger.warning(f"   ⚠️ Position size mismatch detected (orphan position)")
                    logger.warning(f"      Requested: {quantity:.8f}")
                    logger.warning(f"      Available: {available_asset:.8f}")
                    logger.warning(f"   🔧 FIX #5: Adjusting to actual broker balance")
                    quantity = available_asset  # Use actual balance, not stale internal state
                elif available_asset == 0:
                    error_msg = f"No {symbol} balance available to sell (position may already be closed)"
                    logger.warning(f"   ❌ ABORT EXIT: {error_msg}")
                    return False, None, error_msg
                    
            except Exception as refresh_err:
                logger.warning(f"   ⚠️ Could not refresh balances: {refresh_err}")
                logger.warning(f"   Proceeding with emergency sell using provided quantity")
            
            # Get current price for logging purposes
            try:
                current_price = self.broker.get_current_price(symbol)
                estimated_value = current_price * quantity if current_price else 0
                logger.warning(f"   Current Price: ${current_price:.2f}")
                logger.warning(f"   Estimated Value: ${estimated_value:.2f}")
            except Exception as price_err:
                logger.warning(f"   ⚠️ Could not get current price: {price_err}")
                current_price = None
            
            # PROTECTIVE MARKET SELL
            # Use 'base' size type to sell by quantity (not USD amount)
            logger.warning(f"   🛡️ EXECUTING PROTECTIVE MARKET SELL NOW...")
            
            result = self.broker.place_market_order(
                symbol=symbol,
                side='sell',
                quantity=quantity,
                size_type='base'  # Sell by base currency quantity
            )
            
            # Check result
            if result and result.get('status') not in ['error', 'unfilled']:
                logger.warning(f"   ✅ PROTECTIVE SELL SUCCESSFUL")
                logger.warning(f"   Order ID: {result.get('order_id', 'N/A')}")
                logger.warning(f"   Status: {result.get('status', 'N/A')}")
                
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
                
                logger.warning("=" * 80)
                return True, result, ""
            else:
                error_msg = result.get('error', result.get('message', 'Unknown error')) if result else 'No response from broker'
                logger.warning(f"   ❌ PROTECTIVE SELL FAILED: {error_msg}")
                logger.warning(f"   Full result: {result}")
                logger.warning("=" * 80)
                return False, result, error_msg
                
        except Exception as e:
            error_msg = f"Exception during protective sell: {str(e)}"
            logger.warning(f"   ❌ EXCEPTION: {error_msg}")
            logger.warning(f"   Exception type: {type(e).__name__}")
            import traceback
            logger.warning(f"   Traceback: {traceback.format_exc()}")
            logger.warning("=" * 80)
            return False, None, error_msg
    
    def force_sell_multiple_positions(
        self,
        positions: List[Dict],
        reason: str = "Batch protective exit"
    ) -> Dict[str, Tuple[bool, Optional[Dict], str]]:
        """
        Execute protective sells for multiple positions (batch capital preservation).
        
        Args:
            positions: List of position dicts with 'symbol' and 'quantity'
            reason: Reason for the batch protective sell
            
        Returns:
            Dict mapping symbol to (success, result, error_message)
        """
        logger.warning("=" * 80)
        logger.warning(f"🛡️ BATCH PROTECTIVE EXIT: {len(positions)} positions")
        logger.warning(f"   Reason: {reason}")
        logger.warning("=" * 80)
        
        results = {}
        
        for i, position in enumerate(positions, 1):
            symbol = position.get('symbol')
            quantity = position.get('quantity', 0)
            
            if not symbol or quantity <= 0:
                logger.warning(f"[{i}/{len(positions)}] Skipping invalid position: {position}")
                results[symbol] = (False, None, "Invalid position data")
                continue
            
            logger.warning(f"[{i}/{len(positions)}] Protective exit: {symbol}")
            success, result, error = self.force_sell_position(
                symbol=symbol,
                quantity=quantity,
                reason=reason
            )
            
            results[symbol] = (success, result, error)
            
            # Small delay between protective sells to avoid overwhelming the broker
            if i < len(positions):
                time.sleep(0.5)
        
        # Summary
        successful = sum(1 for s, _, _ in results.values() if s)
        failed = len(results) - successful
        
        logger.warning("=" * 80)
        logger.warning(f"🛡️ BATCH PROTECTIVE EXIT COMPLETE")
        logger.warning(f"   Successful: {successful}/{len(positions)}")
        logger.warning(f"   Failed: {failed}/{len(positions)}")
        logger.warning("=" * 80)
        
        return results
    
    def get_execution_history(self) -> List[Dict]:
        """Get history of all protective stop-loss executions."""
        return self.stop_loss_executions.copy()
    
    def clear_execution_history(self):
        """Clear execution history (for testing/reset)."""
        self.stop_loss_executions.clear()
        logger.info("Protective stop-loss execution history cleared")


def create_forced_stop_loss(broker) -> ForcedStopLoss:
    """
    Factory function to create a ForcedStopLoss instance.
    
    Args:
        broker: Broker instance
        
    Returns:
        ForcedStopLoss instance
    """
    return ForcedStopLoss(broker)
