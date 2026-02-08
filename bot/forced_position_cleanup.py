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
from typing import Dict, List, Tuple, Optional
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
                 dry_run: bool = False):
        """
        Initialize forced cleanup engine.
        
        Args:
            dust_threshold_usd: USD value threshold for dust positions
            max_positions: Hard cap on total positions
            dry_run: If True, log actions but don't execute trades
        """
        self.dust_threshold_usd = dust_threshold_usd
        self.max_positions = max_positions
        self.dry_run = dry_run
        
        logger.info("🧹 FORCED POSITION CLEANUP ENGINE INITIALIZED")
        logger.info(f"   Dust Threshold: ${dust_threshold_usd:.2f} USD")
        logger.info(f"   Max Positions: {max_positions}")
        logger.info(f"   Dry Run: {dry_run}")
    
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
            p.get('pnl_pct', 0),  # 2. Worst P&L first
            p.get('entry_time', datetime.now())  # 3. Oldest first
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
    
    def execute_cleanup(self, 
                       positions_to_close: List[Dict],
                       broker,
                       account_id: str = "platform") -> Tuple[int, int]:
        """
        Execute cleanup by closing positions.
        
        Args:
            positions_to_close: List of positions with cleanup metadata
            broker: Broker instance to execute trades
            account_id: Account identifier for logging
        
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
            pnl_pct = pos_data.get('pnl_pct', 0)
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
            
            if self.dry_run:
                logger.warning(f"   [DRY RUN] Would close position")
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
    
    def cleanup_single_account(self,
                               broker,
                               account_id: str = "platform") -> Dict:
        """
        Run forced cleanup on a single account.
        
        Args:
            broker: Broker instance for the account
            account_id: Account identifier for logging
        
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
                dust_positions, broker, account_id
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
                cap_excess_positions, broker, account_id
            )
            cap_closed = cap_success
        
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
    
    def cleanup_all_accounts(self, multi_account_manager) -> Dict:
        """
        Run forced cleanup across all accounts (platform + users).
        
        Args:
            multi_account_manager: MultiAccountBrokerManager instance
        
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
                result = self.cleanup_single_account(broker, account_id)
                results.append(result)
        
        # Cleanup user accounts
        logger.info("")
        logger.info("👥 USER ACCOUNTS")
        logger.info("-" * 70)
        
        for user_id, user_broker_dict in multi_account_manager.user_brokers.items():
            for broker_type, broker in user_broker_dict.items():
                if broker and broker.connected:
                    account_id = f"user_{user_id}_{broker_type.value}"
                    result = self.cleanup_single_account(broker, account_id)
                    results.append(result)
        
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
