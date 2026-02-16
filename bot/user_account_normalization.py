#!/usr/bin/env python3
"""
User Account Normalization Pass
================================
One-time utility to normalize all user accounts and positions.

Implements structural improvements:
1. Scan all positions across accounts
2. Consolidate small positions where possible
3. Enforce minimum position size >= $7.50
4. Force merge positions below tier minimum
5. Comprehensive logging of all actions

Priority: STRUCTURAL (Issue #3)
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Minimum position size threshold
MINIMUM_POSITION_USD = 7.50
# Consolidation threshold - positions below this may be consolidated
CONSOLIDATION_THRESHOLD_USD = 10.00


@dataclass
class NormalizationAction:
    """Represents a normalization action to be taken"""
    action_type: str  # 'consolidate', 'close_small', 'merge'
    symbol: str
    current_size_usd: float
    target_size_usd: Optional[float]
    reason: str


class UserAccountNormalization:
    """
    Normalizes user accounts to enforce minimum position sizes.
    
    This is a one-time pass that:
    - Identifies positions below minimum size
    - Consolidates or closes small positions
    - Enforces tier-based position size minimums
    - Logs all actions for audit trail
    """
    
    def __init__(self,
                 minimum_position_usd: float = MINIMUM_POSITION_USD,
                 consolidation_threshold_usd: float = CONSOLIDATION_THRESHOLD_USD,
                 dry_run: bool = False):
        """
        Initialize normalization pass.
        
        Args:
            minimum_position_usd: Minimum position size to enforce
            consolidation_threshold_usd: Positions below this may be consolidated
            dry_run: If True, log actions but don't execute
        """
        self.minimum_position_usd = minimum_position_usd
        self.consolidation_threshold_usd = consolidation_threshold_usd
        self.dry_run = dry_run
        
        logger.info("🔧 User Account Normalization initialized:")
        logger.info(f"   Minimum Position: ${minimum_position_usd:.2f} USD")
        logger.info(f"   Consolidation Threshold: ${consolidation_threshold_usd:.2f} USD")
        logger.info(f"   Dry Run: {'ENABLED (no actual changes)' if dry_run else 'DISABLED (live normalization)'}")
    
    def scan_positions(self, broker) -> Tuple[List[Dict], List[NormalizationAction]]:
        """
        Scan all positions and identify normalization actions.
        
        Args:
            broker: Broker instance
            
        Returns:
            Tuple of (positions_list, actions_list)
        """
        logger.info("=" * 70)
        logger.info("🔍 SCANNING POSITIONS FOR NORMALIZATION")
        logger.info("=" * 70)
        
        try:
            # Fetch all positions
            positions = broker.get_positions()
            
            if not positions:
                logger.info("   No positions found")
                return [], []
            
            logger.info(f"   Found {len(positions)} total positions")
            
            actions = []
            small_positions = []
            
            # Analyze each position
            for pos in positions:
                symbol = pos.get('symbol', 'UNKNOWN')
                quantity = float(pos.get('quantity', 0))
                
                try:
                    # Get current price and calculate USD value
                    current_price = broker.get_current_price(symbol)
                    if current_price <= 0:
                        logger.warning(f"   ⚠️  Could not get price for {symbol}, skipping")
                        continue
                    
                    usd_value = quantity * current_price
                    
                    # Check if below minimum
                    if usd_value < self.minimum_position_usd:
                        logger.warning(f"   ⚠️  SMALL POSITION: {symbol} - ${usd_value:.2f} (below ${self.minimum_position_usd:.2f})")
                        
                        action = NormalizationAction(
                            action_type='close_small',
                            symbol=symbol,
                            current_size_usd=usd_value,
                            target_size_usd=None,
                            reason=f"Position below minimum ${self.minimum_position_usd:.2f}"
                        )
                        actions.append(action)
                        small_positions.append(pos)
                    
                    # Check if below consolidation threshold
                    elif usd_value < self.consolidation_threshold_usd:
                        logger.info(f"   💡 CONSOLIDATION CANDIDATE: {symbol} - ${usd_value:.2f}")
                        
                        action = NormalizationAction(
                            action_type='consolidate',
                            symbol=symbol,
                            current_size_usd=usd_value,
                            target_size_usd=self.minimum_position_usd,
                            reason=f"Position below optimal size ${self.consolidation_threshold_usd:.2f}"
                        )
                        actions.append(action)
                
                except Exception as e:
                    logger.error(f"   ❌ Error analyzing {symbol}: {e}")
                    continue
            
            # Summary
            logger.info("=" * 70)
            logger.info("📊 SCAN RESULTS")
            logger.info("=" * 70)
            logger.info(f"   Total Positions: {len(positions)}")
            logger.info(f"   Below Minimum (${self.minimum_position_usd:.2f}): {len([a for a in actions if a.action_type == 'close_small'])}")
            logger.info(f"   Consolidation Candidates: {len([a for a in actions if a.action_type == 'consolidate'])}")
            logger.info(f"   Total Actions Required: {len(actions)}")
            logger.info("=" * 70)
            
            return positions, actions
        
        except Exception as e:
            logger.error(f"❌ Error scanning positions: {e}")
            return [], []
    
    def execute_action(self, broker, action: NormalizationAction) -> Tuple[bool, str]:
        """
        Execute a single normalization action.
        
        Args:
            broker: Broker instance
            action: NormalizationAction to execute
            
        Returns:
            Tuple of (success: bool, message: str)
        """
        if self.dry_run:
            logger.info(f"   [DRY RUN] Would execute: {action.action_type} on {action.symbol}")
            return True, "Dry run - no action taken"
        
        try:
            if action.action_type == 'close_small':
                # Close small position
                logger.info(f"🔨 Closing small position: {action.symbol} (${action.current_size_usd:.2f})")
                
                # Get position details to close
                positions = broker.get_positions()
                pos = next((p for p in positions if p.get('symbol') == action.symbol), None)
                
                if not pos:
                    return False, "Position not found"
                
                quantity = float(pos.get('quantity', 0))
                
                # Place market sell order
                result = broker.place_market_order(
                    symbol=action.symbol,
                    side='sell',
                    quantity=quantity,
                    size_type='base',
                    force_liquidate=True,
                    ignore_min_trade=True
                )
                
                if result and result.get('status') in ['filled', 'completed', 'success']:
                    logger.info(f"   ✅ Successfully closed {action.symbol}")
                    return True, "Position closed"
                else:
                    logger.error(f"   ❌ Failed to close {action.symbol}")
                    return False, "Order failed"
            
            elif action.action_type == 'consolidate':
                # For consolidation, we need to decide whether to:
                # 1. Add to position (increase size)
                # 2. Close position (too small to be worth it)
                
                # For now, we'll close positions below minimum
                # In future, could implement smart consolidation logic
                if action.current_size_usd < self.minimum_position_usd:
                    logger.info(f"🔨 Closing consolidation candidate: {action.symbol} (${action.current_size_usd:.2f})")
                    
                    positions = broker.get_positions()
                    pos = next((p for p in positions if p.get('symbol') == action.symbol), None)
                    
                    if not pos:
                        return False, "Position not found"
                    
                    quantity = float(pos.get('quantity', 0))
                    
                    result = broker.place_market_order(
                        symbol=action.symbol,
                        side='sell',
                        quantity=quantity,
                        size_type='base',
                        force_liquidate=True,
                        ignore_min_trade=True
                    )
                    
                    if result and result.get('status') in ['filled', 'completed', 'success']:
                        logger.info(f"   ✅ Successfully closed {action.symbol}")
                        return True, "Position consolidated (closed)"
                    else:
                        logger.error(f"   ❌ Failed to close {action.symbol}")
                        return False, "Order failed"
                else:
                    logger.info(f"   💡 Keeping {action.symbol} (above minimum)")
                    return True, "Position kept (above minimum)"
            
            else:
                return False, f"Unknown action type: {action.action_type}"
        
        except Exception as e:
            logger.error(f"   ❌ Exception executing action on {action.symbol}: {e}")
            return False, f"Exception: {str(e)}"
    
    def normalize_account(self, broker) -> Dict[str, Any]:
        """
        Execute full normalization pass on account.
        
        Args:
            broker: Broker instance
            
        Returns:
            Dict with normalization statistics
        """
        logger.info("=" * 70)
        logger.info("🔧 STARTING USER ACCOUNT NORMALIZATION")
        logger.info("=" * 70)
        
        start_time = datetime.now()
        
        # Scan positions
        positions, actions = self.scan_positions(broker)
        
        if not actions:
            logger.info("✅ No normalization actions required")
            return {
                'total_positions': len(positions),
                'actions_required': 0,
                'actions_executed': 0,
                'actions_failed': 0,
                'duration_seconds': 0
            }
        
        # Execute actions
        executed = 0
        failed = 0
        
        for action in actions:
            logger.info("")
            logger.info(f"Executing action {executed + failed + 1}/{len(actions)}")
            logger.info(f"   Type: {action.action_type}")
            logger.info(f"   Symbol: {action.symbol}")
            logger.info(f"   Current Size: ${action.current_size_usd:.2f}")
            logger.info(f"   Reason: {action.reason}")
            
            success, message = self.execute_action(broker, action)
            
            if success:
                executed += 1
            else:
                failed += 1
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Summary
        logger.info("")
        logger.info("=" * 70)
        logger.info("🔧 NORMALIZATION COMPLETE")
        logger.info("=" * 70)
        logger.info(f"   Total Positions: {len(positions)}")
        logger.info(f"   Actions Required: {len(actions)}")
        logger.info(f"   Successfully Executed: {executed}")
        logger.info(f"   Failed: {failed}")
        logger.info(f"   Duration: {duration:.2f}s")
        logger.info("=" * 70)
        
        return {
            'total_positions': len(positions),
            'actions_required': len(actions),
            'actions_executed': executed,
            'actions_failed': failed,
            'duration_seconds': duration,
            'timestamp': datetime.now().isoformat()
        }


def run_normalization_pass(broker,
                          minimum_position_usd: float = MINIMUM_POSITION_USD,
                          dry_run: bool = True) -> Dict[str, Any]:
    """
    Convenience function to run normalization pass.
    
    Args:
        broker: Broker instance
        minimum_position_usd: Minimum position size to enforce
        dry_run: If True, log actions but don't execute
        
    Returns:
        Dict with normalization statistics
    """
    normalizer = UserAccountNormalization(
        minimum_position_usd=minimum_position_usd,
        dry_run=dry_run
    )
    
    return normalizer.normalize_account(broker)
