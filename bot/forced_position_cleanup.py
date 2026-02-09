#!/usr/bin/env python3
"""
FORCED POSITION CLEANUP ENGINE
==============================
Implements aggressive position cleanup to address critical issues:

1. Force Dust Cleanup - Close ALL positions < $1 USD immediately
2. Retroactive Position Cap - Enforce hard cap by pruning excess positions
3. Multi-Account Support - Clean up both platform and user accounts

This runs independently of the trading loop to ensure cleanup happens
even when trading is paused or positions were adopted from legacy holdings.
"""

import logging
import time
import os
from typing import Dict, List, Tuple, Optional, Union, Any
from datetime import datetime
from enum import Enum

logger = logging.getLogger("nija.cleanup")


class CleanupType(Enum):
    """Types of cleanup operations"""
    DUST = "DUST"  # Position < $1 USD
    CAP_EXCEEDED = "CAP_EXCEEDED"  # Over position limit
    UNHEALTHY = "UNHEALTHY"  # Low health score
    STAGNANT = "STAGNANT"  # No movement


class ForcedPositionCleanup:
    """
    Forces aggressive cleanup of dust positions and enforces hard position caps.
    
    Key Features:
    - Closes ALL positions < $1 USD (dust threshold)
    - Prunes excess positions to enforce hard cap retroactively
    - Supports multi-account cleanup (platform + users)
    - Comprehensive logging with profit status tracking
    """
    
    def __init__(self,
                 dust_threshold_usd: float = 1.00,
                 max_positions: int = 8,
                 dry_run: bool = False,
                 cancel_open_orders: bool = False,
                 startup_only: bool = False,
                 cancel_conditions: Optional[str] = None):
        """
        Initialize forced cleanup engine.
        
        Args:
            dust_threshold_usd: USD value threshold for dust positions
            max_positions: Hard cap on total positions
            dry_run: If True, log actions but don't execute trades
            cancel_open_orders: If True, cancel open orders during cleanup
            startup_only: If True with cancel_open_orders, only cancel on first run (nuclear mode)
            cancel_conditions: Selective cancellation conditions (e.g., "usd_value<1.0,rank>max_positions")
        """
        self.dust_threshold_usd = dust_threshold_usd
        self.max_positions = max_positions
        self.dry_run = dry_run
        self.has_run_startup = False  # Track if startup cleanup has run
        
        # Parse cancel_conditions if provided
        self.cancel_conditions = self._parse_cancel_conditions(cancel_conditions) if cancel_conditions else None
        
        # If cancel_conditions are provided, automatically enable cancel_open_orders
        if self.cancel_conditions:
            self.cancel_open_orders = True
            self.startup_only = startup_only
        else:
            self.cancel_open_orders = cancel_open_orders
            self.startup_only = startup_only
        
        # Load config from environment if not explicitly set via parameters
        # Only override if no explicit config was provided
        if not cancel_open_orders and not cancel_conditions:
            env_cancel = os.getenv('FORCED_CLEANUP_CANCEL_OPEN_ORDERS', 'false').lower() in ['true', '1', 'yes']
            env_startup_only = os.getenv('FORCED_CLEANUP_STARTUP_ONLY', 'false').lower() in ['true', '1', 'yes']
            env_conditions = os.getenv('FORCED_CLEANUP_CANCEL_OPEN_ORDERS_IF', '')
            
            if env_conditions:
                self.cancel_conditions = self._parse_cancel_conditions(env_conditions)
                self.cancel_open_orders = True  # Enable if conditions specified
            else:
                self.cancel_open_orders = env_cancel
            
            self.startup_only = env_startup_only
        
        logger.info("🧹 FORCED POSITION CLEANUP ENGINE INITIALIZED")
        logger.info(f"   Dust Threshold: ${dust_threshold_usd:.2f} USD")
        logger.info(f"   Max Positions: {max_positions}")
        logger.info(f"   Dry Run: {dry_run}")
        logger.info(f"   Cancel Open Orders: {self.cancel_open_orders}")
        if self.cancel_open_orders:
            if self.cancel_conditions:
                logger.info(f"   Cancellation Mode: SELECTIVE (conditions: {self.cancel_conditions})")
            elif self.startup_only:
                logger.info(f"   Cancellation Mode: NUCLEAR (startup-only)")
            else:
                logger.info(f"   Cancellation Mode: ALWAYS")
    
    def _parse_cancel_conditions(self, conditions_str: str) -> Dict[str, Union[float, bool]]:
        """
        Parse cancellation conditions from string format.
        
        Format: "usd_value<1.0,rank>max_positions"
        
        Supported conditions:
        - usd_value<X: Cancel if position USD value < X (float)
        - rank>max_positions: Cancel if position ranked for cap pruning (bool)
        
        Returns:
            Dict with parsed conditions (values can be float or bool).
            Returns empty dict if conditions_str is empty or all conditions are malformed.
        
        Error handling:
        - Malformed conditions are skipped with warning logs
        - Invalid numeric values are skipped with warnings
        - Missing operators are skipped with warnings
        """
        conditions = {}
        if not conditions_str:
            return conditions
        
        for condition in conditions_str.split(','):
            condition = condition.strip()
            
            try:
                if '<' in condition:
                    parts = condition.split('<')
                    if len(parts) != 2:
                        logger.warning(f"   ⚠️  Malformed condition (expected one '<'): {condition}")
                        continue
                    key, value = parts
                    try:
                        conditions[key.strip()] = float(value.strip())
                    except ValueError:
                        logger.warning(f"   ⚠️  Invalid numeric value in condition: {condition}")
                        continue
                elif '>' in condition:
                    parts = condition.split('>')
                    if len(parts) != 2:
                        logger.warning(f"   ⚠️  Malformed condition (expected one '>'): {condition}")
                        continue
                    key, value = parts
                    if value.strip() == 'max_positions':
                        conditions['rank_exceeds_cap'] = True
                    else:
                        logger.warning(f"   ⚠️  Unsupported '>' condition value: {value.strip()}")
                else:
                    logger.warning(f"   ⚠️  Condition missing operator ('<' or '>'): {condition}")
            except Exception as e:
                logger.warning(f"   ⚠️  Error parsing condition '{condition}': {e}")
                continue
        
        return conditions
    
    def _should_cancel_open_orders(self, position_data: Dict, is_startup: bool = False) -> bool:
        """
        Determine if open orders should be cancelled for this position.
        
        Args:
            position_data: Position data with cleanup metadata
            is_startup: Whether this is a startup cleanup
        
        Returns:
            True if open orders should be cancelled
        """
        # If open order cancellation is disabled, never cancel
        if not self.cancel_open_orders:
            return False
        
        # If startup-only mode and this is not startup, don't cancel
        if self.startup_only and not is_startup:
            return False
        
        # If startup-only mode and startup already ran, don't cancel
        if self.startup_only and self.has_run_startup:
            return False
        
        # If selective conditions are set, check them
        if self.cancel_conditions:
            size_usd = position_data.get('size_usd', 0)
            cleanup_type = position_data.get('cleanup_type', '')
            
            # Check USD value condition
            if 'usd_value' in self.cancel_conditions:
                if size_usd < self.cancel_conditions['usd_value']:
                    return True
            
            # Check rank condition (cap exceeded positions)
            if 'rank_exceeds_cap' in self.cancel_conditions:
                if cleanup_type == CleanupType.CAP_EXCEEDED.value:
                    return True
            
            # If conditions exist but none matched, don't cancel
            return False
        
        # Default: cancel if enabled and not in selective mode
        return True
    
    def identify_dust_positions(self, positions: List[Dict]) -> List[Dict]:
        """
        Identify all positions below dust threshold.
        
        Args:
            positions: List of position dicts with 'symbol', 'size_usd', 'pnl_pct'
        
        Returns:
            List of dust positions with cleanup metadata
        """
        dust_positions = []
        
        for pos in positions:
            size_usd = pos.get('size_usd', 0) or pos.get('usd_value', 0)
            
            if size_usd > 0 and size_usd < self.dust_threshold_usd:
                dust_positions.append({
                    'symbol': pos['symbol'],
                    'size_usd': size_usd,
                    'pnl_pct': pos.get('pnl_pct', 0),
                    'cleanup_type': CleanupType.DUST.value,
                    'reason': f'Dust position (${size_usd:.2f} < ${self.dust_threshold_usd:.2f})',
                    'priority': 'HIGH'
                })
        
        return dust_positions
    
    def identify_cap_excess_positions(self, positions: List[Dict]) -> List[Dict]:
        """
        Identify positions to close when over the hard cap.
        
        Ranking criteria (in order):
        1. Lowest USD value (minimize capital impact)
        2. Worst P&L (cut losers first)
        3. Oldest age (if available)
        
        Args:
            positions: List of position dicts
        
        Returns:
            List of positions to close to meet cap
        """
        if len(positions) <= self.max_positions:
            return []
        
        excess_count = len(positions) - self.max_positions
        
        # Sort by ranking criteria
        ranked_positions = sorted(positions, key=lambda p: (
            p.get('size_usd', 0) or p.get('usd_value', 0),  # 1. Smallest first
            p.get('pnl_pct', 0) or 0,  # 2. Worst P&L first (handle None)
            -(p.get('entry_time', datetime.min).timestamp() if isinstance(p.get('entry_time'), datetime) else 0)  # 3. Oldest first (use min for missing dates)
        ))
        
        excess_positions = []
        for i in range(excess_count):
            pos = ranked_positions[i]
            excess_positions.append({
                'symbol': pos['symbol'],
                'size_usd': pos.get('size_usd', 0) or pos.get('usd_value', 0),
                'pnl_pct': pos.get('pnl_pct', 0),
                'cleanup_type': CleanupType.CAP_EXCEEDED.value,
                'reason': f'Position cap exceeded ({len(positions)}/{self.max_positions})',
                'priority': 'HIGH'
            })
        
        return excess_positions
    
    def _get_open_orders_for_symbol(self, broker, symbol: str) -> List[Dict]:
        """
        Get open orders for a specific symbol.
        
        Handles broker API inconsistencies:
        - Some brokers use 'symbol' field (Coinbase, Alpaca)
        - Some brokers use 'pair' field (Kraken)
        
        Args:
            broker: Broker instance
            symbol: Trading symbol
        
        Returns:
            List of open order dicts
        """
        try:
            # Try to get all open orders
            if hasattr(broker, 'get_open_orders'):
                all_orders = broker.get_open_orders()
                if all_orders:
                    # Filter for this symbol (check both 'symbol' and 'pair' for compatibility)
                    return [order for order in all_orders if order.get('symbol') == symbol or order.get('pair') == symbol]
            
            # Fallback: check if broker has symbol-specific method
            if hasattr(broker, 'get_open_orders_for_symbol'):
                return broker.get_open_orders_for_symbol(symbol)
            
            return []
        except Exception as e:
            logger.warning(f"   ⚠️  Failed to get open orders for {symbol}: {e}")
            return []
    
    def _cancel_open_orders_for_symbol(self, broker, symbol: str, is_startup: bool = False) -> Tuple[int, int]:
        """
        Cancel all open orders for a symbol.
        
        Handles broker API inconsistencies for order ID field names:
        - Coinbase: uses 'id' field
        - Kraken: uses 'txid' field  
        - Alpaca: uses 'order_id' or 'id' field
        
        Args:
            broker: Broker instance
            symbol: Trading symbol
            is_startup: Whether this is a startup cleanup
        
        Returns:
            Tuple of (cancelled_count, failed_count)
        """
        open_orders = self._get_open_orders_for_symbol(broker, symbol)
        
        if not open_orders:
            return 0, 0
        
        cancelled = 0
        failed = 0
        
        for order in open_orders:
            # Try multiple field names for order ID (broker-specific)
            order_id = order.get('id') or order.get('order_id') or order.get('txid')
            if not order_id:
                logger.warning(f"   ⚠️  No order ID found for order on {symbol}")
                failed += 1
                continue
            
            try:
                if self.dry_run:
                    logger.warning(f"   [DRY RUN][OPEN_ORDER][WOULD_CANCEL] Order {order_id} on {symbol}")
                    cancelled += 1
                else:
                    logger.warning(f"   [OPEN_ORDER][CANCELLING] Order {order_id} on {symbol}")
                    if hasattr(broker, 'cancel_order'):
                        result = broker.cancel_order(order_id)
                        if result:
                            logger.warning(f"   ✅ [OPEN_ORDER][CANCELLED] Order {order_id}")
                            cancelled += 1
                        else:
                            logger.error(f"   ❌ [OPEN_ORDER][CANCEL_FAILED] Order {order_id}")
                            failed += 1
                    else:
                        logger.warning(f"   ⚠️  Broker does not support order cancellation")
                        failed += 1
                
                # Rate limiting
                time.sleep(0.3)
            except Exception as e:
                logger.error(f"   ❌ [OPEN_ORDER][CANCEL_FAILED] Order {order_id}: {e}")
                failed += 1
        
        return cancelled, failed
    
    def execute_cleanup(self, 
                       positions_to_close: List[Dict],
                       broker,
                       account_id: str = "platform",
                       is_startup: bool = False) -> Tuple[int, int]:
        """
        Execute cleanup by closing positions and optionally cancelling open orders.
        
        Args:
            positions_to_close: List of positions with cleanup metadata
            broker: Broker instance to execute trades
            account_id: Account identifier for logging
            is_startup: Whether this is a startup cleanup
        
        Returns:
            Tuple of (successful_closes, failed_closes)
        """
        if not positions_to_close:
            return 0, 0
        
        logger.warning(f"")
        logger.warning(f"🧹 EXECUTING FORCED CLEANUP: {account_id}")
        logger.warning(f"   Positions to close: {len(positions_to_close)}")
        logger.warning(f"")
        
        successful = 0
        failed = 0
        
        for pos_data in positions_to_close:
            symbol = pos_data['symbol']
            cleanup_type = pos_data['cleanup_type']
            reason = pos_data['reason']
            pnl_pct = pos_data.get('pnl_pct', 0) or 0  # Handle None values
            size_usd = pos_data.get('size_usd', 0)
            
            outcome = "WIN" if pnl_pct > 0 else "LOSS"
            
            logger.warning(f"")
            logger.warning(f"🧹 [{cleanup_type}][FORCED] {symbol}")
            logger.warning(f"   Account: {account_id}")
            logger.warning(f"   Reason: {reason}")
            logger.warning(f"   Size: ${size_usd:.2f}")
            logger.warning(f"   P&L: {pnl_pct*100:+.2f}%")
            logger.warning(f"   PROFIT_STATUS = PENDING → CONFIRMED")
            logger.warning(f"   OUTCOME = {outcome}")
            
            # Check if we should cancel open orders for this position
            should_cancel = self._should_cancel_open_orders(pos_data, is_startup)
            
            if should_cancel:
                logger.warning(f"   🔍 Checking for open orders...")
                cancelled, cancel_failed = self._cancel_open_orders_for_symbol(broker, symbol, is_startup)
                if cancelled > 0:
                    logger.warning(f"   ✅ Cancelled {cancelled} open order(s)")
                if cancel_failed > 0:
                    logger.warning(f"   ⚠️  Failed to cancel {cancel_failed} open order(s)")
            
            if self.dry_run:
                if should_cancel:
                    logger.warning(f"   [DRY RUN][WOULD_CLOSE] Position (after cancelling open orders)")
                else:
                    logger.warning(f"   [DRY RUN][WOULD_CLOSE] Position")
                successful += 1
                continue
            
            try:
                # Attempt to close the position
                result = broker.close_position(symbol)
                
                if result and result.get('status') in ['filled', 'success']:
                    logger.warning(f"   ✅ CLOSED SUCCESSFULLY")
                    successful += 1
                else:
                    error = result.get('error', 'Unknown error') if result else 'No result'
                    logger.error(f"   ❌ CLOSE FAILED: {error}")
                    failed += 1
                
                # Rate limiting
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"   ❌ CLOSE FAILED: {e}")
                failed += 1
        
        logger.warning(f"")
        logger.warning(f"🧹 CLEANUP COMPLETE: {account_id}")
        logger.warning(f"   Successful: {successful}")
        logger.warning(f"   Failed: {failed}")
        logger.warning(f"")
        
        return successful, failed
    
    def _cleanup_user_all_brokers(self, 
                                  user_id: str,
                                  user_broker_dict: Dict,
                                  is_startup: bool = False) -> List[Dict]:
        """
        Cleanup positions for a single user across ALL their brokers.
        
        CRITICAL: Enforces position cap PER USER (not per broker).
        If a user has multiple brokers, we count positions across all brokers
        and enforce the cap at the user level.
        
        Args:
            user_id: User identifier
            user_broker_dict: Dict of {BrokerType: BaseBroker} for this user
            is_startup: Whether this is a startup cleanup
        
        Returns:
            List of cleanup results (one per broker)
        """
        logger.info(f"")
        logger.info(f"👤 USER: {user_id}")
        logger.info(f"-" * 70)
        
        # Step 1: Collect all positions across all user's brokers
        all_user_positions = []
        broker_positions_map = {}  # Maps position symbol to broker instance
        
        for broker_type, broker in user_broker_dict.items():
            if not broker or not broker.connected:
                continue
                
            try:
                positions = broker.get_positions()
                for pos in positions:
                    # Track which broker owns each position
                    symbol = pos.get('symbol', '')
                    if symbol:
                        all_user_positions.append(pos)
                        broker_positions_map[symbol] = broker
            except Exception as e:
                logger.warning(f"   ⚠️ Failed to get positions from {broker_type.value}: {e}")
        
        total_user_positions = len(all_user_positions)
        logger.info(f"   📊 Active Positions: {total_user_positions} (across {len(user_broker_dict)} broker(s))")
        
        # Step 2: First pass - identify and close dust positions across all brokers
        dust_positions = self.identify_dust_positions(all_user_positions)
        dust_closed_total = 0
        
        if dust_positions:
            logger.warning(f"   🧹 Found {len(dust_positions)} dust positions")
            for dust_pos in dust_positions:
                symbol = dust_pos['symbol']
                broker = broker_positions_map.get(symbol)
                if broker:
                    account_id = f"user_{user_id}_{broker.broker_type.value if hasattr(broker, 'broker_type') else 'unknown'}"
                    success, failed = self.execute_cleanup([dust_pos], broker, account_id, is_startup)
                    dust_closed_total += success
        
        # Step 3: Refresh positions after dust cleanup
        all_user_positions = []
        broker_positions_map = {}
        
        for broker_type, broker in user_broker_dict.items():
            if not broker or not broker.connected:
                continue
                
            try:
                positions = broker.get_positions()
                for pos in positions:
                    symbol = pos.get('symbol', '')
                    if symbol:
                        all_user_positions.append(pos)
                        broker_positions_map[symbol] = broker
            except Exception as e:
                logger.warning(f"   ⚠️ Failed to refresh positions from {broker_type.value}: {e}")
        
        # Filter out dust from cap check
        non_dust_positions = [
            p for p in all_user_positions 
            if (p.get('size_usd', 0) or p.get('usd_value', 0)) >= self.dust_threshold_usd
        ]
        
        # Step 4: Enforce per-user position cap across all brokers
        cap_closed_total = 0
        current_count = len(non_dust_positions)
        
        logger.info(f"   📊 Active Positions (after dust cleanup): {current_count}")
        
        if current_count > self.max_positions:
            logger.warning(f"   🔒 Position cap exceeded: {current_count}/{self.max_positions}")
            
            # Identify positions to close to meet cap
            cap_excess_positions = self.identify_cap_excess_positions(non_dust_positions)
            
            # Close excess positions across all brokers
            for cap_pos in cap_excess_positions:
                symbol = cap_pos['symbol']
                broker = broker_positions_map.get(symbol)
                if broker:
                    account_id = f"user_{user_id}_{broker.broker_type.value if hasattr(broker, 'broker_type') else 'unknown'}"
                    success, failed = self.execute_cleanup([cap_pos], broker, account_id, is_startup)
                    cap_closed_total += success
        else:
            logger.info(f"   ✅ Under cap (no action needed)")
        
        # Step 5: Final position count for this user
        all_user_positions_final = []
        for broker_type, broker in user_broker_dict.items():
            if not broker or not broker.connected:
                continue
            try:
                positions = broker.get_positions()
                all_user_positions_final.extend(positions)
            except Exception:
                pass
        
        final_count = len(all_user_positions_final)
        
        logger.info(f"")
        logger.info(f"   👤 USER {user_id} SUMMARY:")
        logger.info(f"      Initial: {total_user_positions} positions")
        logger.info(f"      Dust closed: {dust_closed_total}")
        logger.info(f"      Cap excess closed: {cap_closed_total}")
        logger.info(f"      Final: {final_count} positions")
        logger.info(f"")
        
        # Return results for each broker (for compatibility with existing summary)
        results = []
        for broker_type, broker in user_broker_dict.items():
            if broker and broker.connected:
                account_id = f"user_{user_id}_{broker_type.value}"
                # Note: We already did cleanup above, so just report final state
                try:
                    final_positions = broker.get_positions()
                    results.append({
                        'account_id': account_id,
                        'user_id': user_id,
                        'initial_positions': total_user_positions,  # User total, not broker
                        'dust_closed': dust_closed_total if broker_type == list(user_broker_dict.keys())[0] else 0,  # Report once
                        'cap_closed': cap_closed_total if broker_type == list(user_broker_dict.keys())[0] else 0,  # Report once
                        'final_positions': len(final_positions),  # Per broker
                        'status': 'cleaned'
                    })
                except Exception:
                    results.append({
                        'account_id': account_id,
                        'user_id': user_id,
                        'initial_positions': 0,
                        'dust_closed': 0,
                        'cap_closed': 0,
                        'final_positions': 0,
                        'status': 'error'
                    })
        
        return results

    def cleanup_single_account(self,
                               broker,
                               account_id: str = "platform",
                               is_startup: bool = False) -> Dict:
        """
        Run forced cleanup on a single account.
        
        Args:
            broker: Broker instance for the account
            account_id: Account identifier for logging
            is_startup: Whether this is a startup cleanup
        
        Returns:
            Cleanup result summary
        """
        logger.info(f"🔍 Scanning account: {account_id}")
        
        if not broker or not hasattr(broker, 'get_positions'):
            logger.error(f"   ❌ Invalid broker for {account_id}")
            return {
                'account_id': account_id,
                'initial_positions': 0,
                'dust_closed': 0,
                'cap_closed': 0,
                'final_positions': 0,
                'status': 'error'
            }
        
        # Get current positions
        try:
            positions = broker.get_positions()
        except Exception as e:
            logger.error(f"   ❌ Failed to get positions: {e}")
            return {
                'account_id': account_id,
                'initial_positions': 0,
                'dust_closed': 0,
                'cap_closed': 0,
                'final_positions': 0,
                'status': 'error'
            }
        
        initial_count = len(positions)
        logger.info(f"   Initial positions: {initial_count}")
        
        if initial_count == 0:
            logger.info(f"   ✅ No positions to clean up")
            return {
                'account_id': account_id,
                'initial_positions': 0,
                'dust_closed': 0,
                'cap_closed': 0,
                'final_positions': 0,
                'status': 'clean'
            }
        
        # Step 1: Identify and close dust positions
        dust_positions = self.identify_dust_positions(positions)
        dust_closed = 0
        if dust_positions:
            logger.warning(f"   🧹 Found {len(dust_positions)} dust positions")
            dust_success, dust_fail = self.execute_cleanup(
                dust_positions, broker, account_id, is_startup
            )
            dust_closed = dust_success
        
        # Step 2: Refresh positions and check cap
        try:
            positions = broker.get_positions()
        except Exception as e:
            logger.error(f"   ❌ Failed to refresh positions: {e}")
            positions = []
        
        # Filter out dust positions from cap check
        non_dust_positions = [
            p for p in positions 
            if (p.get('size_usd', 0) or p.get('usd_value', 0)) >= self.dust_threshold_usd
        ]
        
        cap_excess_positions = self.identify_cap_excess_positions(non_dust_positions)
        cap_closed = 0
        if cap_excess_positions:
            logger.warning(f"   🔒 Position cap exceeded: {len(non_dust_positions)}/{self.max_positions}")
            cap_success, cap_fail = self.execute_cleanup(
                cap_excess_positions, broker, account_id, is_startup
            )
            cap_closed = cap_success
        
        # Mark startup as complete if this was a startup cleanup
        if is_startup:
            self.has_run_startup = True
        
        # Final position count
        try:
            final_positions = broker.get_positions()
            final_count = len(final_positions)
        except Exception:
            final_count = initial_count - dust_closed - cap_closed
        
        return {
            'account_id': account_id,
            'initial_positions': initial_count,
            'dust_closed': dust_closed,
            'cap_closed': cap_closed,
            'final_positions': final_count,
            'status': 'cleaned'
        }
    
    def cleanup_all_accounts(self, multi_account_manager, is_startup: bool = False) -> Dict:
        """
        Run forced cleanup across all accounts (platform + users).
        
        CRITICAL: Enforces position caps PER USER across all their brokers.
        Each user is limited to max_positions (default 8) total positions.
        
        Args:
            multi_account_manager: MultiAccountBrokerManager instance
            is_startup: Whether this is a startup cleanup
        
        Returns:
            Summary of cleanup across all accounts
        """
        logger.warning("=" * 70)
        logger.warning("🧹 FORCED CLEANUP: ALL ACCOUNTS")
        logger.warning("=" * 70)
        
        results = []
        
        # Cleanup platform accounts
        logger.info("")
        logger.info("📊 PLATFORM ACCOUNTS")
        logger.info("-" * 70)
        
        for broker_type, broker in multi_account_manager.platform_brokers.items():
            if broker and broker.connected:
                account_id = f"platform_{broker_type.value}"
                result = self.cleanup_single_account(broker, account_id, is_startup)
                results.append(result)
        
        # Cleanup user accounts - ENFORCE PER-USER POSITION CAPS
        logger.info("")
        logger.info("👥 USER ACCOUNTS")
        logger.info("-" * 70)
        
        for user_id, user_broker_dict in multi_account_manager.user_brokers.items():
            # Process all brokers for this user together to enforce per-user cap
            user_result = self._cleanup_user_all_brokers(
                user_id, 
                user_broker_dict, 
                is_startup
            )
            results.extend(user_result)
        
        # Summary
        total_initial = sum(r['initial_positions'] for r in results)
        total_dust = sum(r['dust_closed'] for r in results)
        total_cap = sum(r['cap_closed'] for r in results)
        total_final = sum(r['final_positions'] for r in results)
        
        logger.warning("")
        logger.warning("=" * 70)
        logger.warning("🧹 CLEANUP SUMMARY - ALL ACCOUNTS")
        logger.warning("=" * 70)
        logger.warning(f"   Accounts processed: {len(results)}")
        logger.warning(f"   Initial total positions: {total_initial}")
        logger.warning(f"   Dust positions closed: {total_dust}")
        logger.warning(f"   Cap excess closed: {total_cap}")
        logger.warning(f"   Final total positions: {total_final}")
        logger.warning(f"   Total reduced by: {total_initial - total_final}")
        logger.warning("=" * 70)
        logger.warning("")
        
        return {
            'accounts_processed': len(results),
            'initial_total': total_initial,
            'dust_closed': total_dust,
            'cap_closed': total_cap,
            'final_total': total_final,
            'reduction': total_initial - total_final,
            'details': results
        }


# Example standalone usage
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
    )
    
    # Example: Test with mock positions
    cleanup = ForcedPositionCleanup(
        dust_threshold_usd=1.00,
        max_positions=8,
        dry_run=True
    )
    
    # Mock positions
    mock_positions = [
        {'symbol': 'BTC-USD', 'size_usd': 50.0, 'pnl_pct': 0.02},
        {'symbol': 'ETH-USD', 'size_usd': 0.50, 'pnl_pct': -0.01},  # Dust
        {'symbol': 'SOL-USD', 'size_usd': 30.0, 'pnl_pct': 0.01},
        {'symbol': 'MATIC-USD', 'size_usd': 0.75, 'pnl_pct': 0.005},  # Dust
        {'symbol': 'AVAX-USD', 'size_usd': 25.0, 'pnl_pct': -0.015},
        {'symbol': 'DOT-USD', 'size_usd': 20.0, 'pnl_pct': 0.008},
        {'symbol': 'LINK-USD', 'size_usd': 15.0, 'pnl_pct': -0.02},
        {'symbol': 'UNI-USD', 'size_usd': 10.0, 'pnl_pct': 0.005},
        {'symbol': 'AAVE-USD', 'size_usd': 5.0, 'pnl_pct': -0.01},
        {'symbol': 'ATOM-USD', 'size_usd': 3.0, 'pnl_pct': 0.003},  # 10th position (over cap)
    ]
    
    # Test dust identification
    dust = cleanup.identify_dust_positions(mock_positions)
    logger.info(f"\n🧹 Dust positions identified: {len(dust)}")
    
    # Test cap excess identification
    cap_excess = cleanup.identify_cap_excess_positions(mock_positions)
    logger.info(f"🔒 Cap excess positions: {len(cap_excess)}")
