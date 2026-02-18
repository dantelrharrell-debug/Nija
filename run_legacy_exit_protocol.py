#!/usr/bin/env python3
"""
Run Legacy Position Exit Protocol
==================================
Command-line interface to execute the Legacy Position Exit Protocol.

Usage:
    python run_legacy_exit_protocol.py [options]

Options:
    --broker BROKER         Broker name (coinbase, kraken, alpaca) [default: coinbase]
    --max-positions N       Maximum positions allowed [default: 8]
    --dust-pct PCT         Dust threshold as % of account [default: 0.01]
    --stale-minutes MIN    Minutes before order is stale [default: 30]
    --user-id ID           User ID for multi-account (optional)
    --dry-run              Simulate without executing trades
    --phase PHASE          Run specific phase only (1, 2, 3, 4, or 'all') [default: all]
    --verify-only          Only run Phase 4 verification

Examples:
    # Run full protocol on Coinbase
    python run_legacy_exit_protocol.py --broker coinbase
    
    # Verify clean state only
    python run_legacy_exit_protocol.py --verify-only
    
    # Run Phase 2 (order cleanup) only
    python run_legacy_exit_protocol.py --phase 2
    
    # Dry run with custom settings
    python run_legacy_exit_protocol.py --max-positions 10 --dust-pct 0.02 --dry-run
"""

import sys
import os
import argparse
import logging
from pathlib import Path

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent / 'bot'))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description='Run Legacy Position Exit Protocol',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument('--broker', default='coinbase',
                       choices=['coinbase', 'kraken', 'alpaca'],
                       help='Broker name (default: coinbase)')
    parser.add_argument('--max-positions', type=int, default=8,
                       help='Maximum positions allowed (default: 8)')
    parser.add_argument('--dust-pct', type=float, default=0.01,
                       help='Dust threshold as %% of account (default: 0.01 = 1%%)')
    parser.add_argument('--stale-minutes', type=int, default=30,
                       help='Minutes before order is stale (default: 30)')
    parser.add_argument('--user-id', type=str, default=None,
                       help='User ID for multi-account (optional)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Simulate without executing trades')
    parser.add_argument('--phase', type=str, default='all',
                       choices=['1', '2', '3', '4', 'all'],
                       help='Run specific phase only (default: all)')
    parser.add_argument('--verify-only', action='store_true',
                       help='Only run Phase 4 verification')
    
    args = parser.parse_args()
    
    # Import modules
    try:
        from bot.position_tracker import PositionTracker
        from bot.broker_integration import get_broker_integration
        from bot.legacy_position_exit_protocol import LegacyPositionExitProtocol, AccountState
    except ImportError as e:
        logger.error(f"Failed to import required modules: {e}")
        logger.error("Make sure you're running from the repository root")
        return 1
    
    # Initialize components
    logger.info("=" * 80)
    logger.info("🎯 LEGACY POSITION EXIT PROTOCOL")
    logger.info("=" * 80)
    logger.info(f"Broker: {args.broker}")
    logger.info(f"Max Positions: {args.max_positions}")
    logger.info(f"Dust Threshold: {args.dust_pct * 100:.1f}% of account")
    logger.info(f"Stale Order Age: {args.stale_minutes} minutes")
    if args.user_id:
        logger.info(f"User ID: {args.user_id}")
    if args.dry_run:
        logger.info("🔒 DRY RUN MODE: No trades will be executed")
    logger.info("=" * 80 + "\n")
    
    try:
        # Initialize position tracker
        position_tracker = PositionTracker(storage_file="data/positions.json")
        
        # Get broker integration
        broker = get_broker_integration(args.broker, dry_run=args.dry_run)
        
        # Initialize protocol
        protocol = LegacyPositionExitProtocol(
            position_tracker=position_tracker,
            broker_integration=broker,
            max_positions=args.max_positions,
            dust_pct_threshold=args.dust_pct,
            stale_order_minutes=args.stale_minutes,
            data_dir="./data"
        )
        
        # Execute protocol based on args
        if args.verify_only:
            # Only run verification
            logger.info("Running verification only...\n")
            state, diagnostics = protocol.verify_clean_state(user_id=args.user_id)
            
            if state == AccountState.CLEAN:
                logger.info("✅ Account is CLEAN")
                return 0
            else:
                logger.warning("⚠️  Account needs cleanup")
                return 1
        
        elif args.phase == 'all':
            # Run full protocol
            results = protocol.run_full_protocol(user_id=args.user_id)
            
            if results.get('success'):
                logger.info("✅ Protocol completed successfully")
                return 0
            else:
                logger.warning("⚠️  Protocol completed with issues")
                return 1
        
        else:
            # Run specific phase
            phase_num = int(args.phase)
            
            # Get current data
            positions = broker.get_open_positions(user_id=args.user_id)
            account_balance = broker.get_account_balance(user_id=args.user_id)
            
            if phase_num == 1:
                logger.info("Running Phase 1: Position Classification\n")
                classified = protocol.classify_all_positions(positions, account_balance)
                logger.info(f"✅ Classified {len(classified)} positions")
                
            elif phase_num == 2:
                logger.info("Running Phase 2: Order Cleanup\n")
                cancelled, freed = protocol.cancel_stale_orders(user_id=args.user_id)
                logger.info(f"✅ Cancelled {cancelled} orders, freed ${freed:.2f}")
                
            elif phase_num == 3:
                logger.info("Running Phase 3: Controlled Exits\n")
                # Need classification first
                classified = protocol.classify_all_positions(positions, account_balance)
                exit_results = protocol.execute_controlled_exits(classified, account_balance)
                successful = sum(1 for v in exit_results.values() if v)
                logger.info(f"✅ Processed {len(exit_results)} positions ({successful} successful)")
                
            elif phase_num == 4:
                logger.info("Running Phase 4: Clean State Verification\n")
                state, diagnostics = protocol.verify_clean_state(user_id=args.user_id)
                
                if state == AccountState.CLEAN:
                    logger.info("✅ Account is CLEAN")
                    return 0
                else:
                    logger.warning("⚠️  Account needs cleanup")
                    return 1
            
            return 0
            
    except Exception as e:
        logger.error(f"❌ Error executing protocol: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
