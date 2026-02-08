#!/usr/bin/env python3
"""
EMERGENCY FORCED CLEANUP SCRIPT
================================
Run this script to immediately execute forced cleanup across all accounts.

This will:
1. Close ALL positions < $1 USD (dust cleanup)
2. Enforce hard position cap by closing excess positions
3. Work across both platform and user accounts

Usage:
    python3 run_forced_cleanup.py              # Execute cleanup
    python3 run_forced_cleanup.py --dry-run    # Preview what would be closed
    python3 run_forced_cleanup.py --help       # Show help
"""

import os
import sys
import logging
import argparse
from datetime import datetime

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
)

logger = logging.getLogger("nija.cleanup")


def main():
    """Main entry point for forced cleanup script"""
    parser = argparse.ArgumentParser(
        description='Force cleanup of dust positions and enforce position cap across all accounts',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 run_forced_cleanup.py                    # Execute cleanup
  python3 run_forced_cleanup.py --dry-run          # Preview only
  python3 run_forced_cleanup.py --dust 0.50        # Custom dust threshold
  python3 run_forced_cleanup.py --max-positions 5  # Custom position cap

Safety:
  - Dry run mode is safe and shows what would be closed
  - Live mode requires confirmation before executing
  - All actions are logged with profit status tracking
        """
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview mode - show what would be closed without executing'
    )
    
    parser.add_argument(
        '--dust',
        type=float,
        default=1.00,
        help='Dust threshold in USD (default: 1.00)'
    )
    
    parser.add_argument(
        '--max-positions',
        type=int,
        default=8,
        help='Maximum positions allowed (default: 8)'
    )
    
    parser.add_argument(
        '--yes',
        action='store_true',
        help='Skip confirmation prompt (auto-confirm)'
    )
    
    args = parser.parse_args()
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("🧹 NIJA FORCED POSITION CLEANUP")
    logger.info("=" * 70)
    logger.info(f"   Mode: {'DRY RUN (Preview)' if args.dry_run else 'LIVE (Execute)'}")
    logger.info(f"   Dust Threshold: ${args.dust:.2f} USD")
    logger.info(f"   Max Positions: {args.max_positions}")
    logger.info(f"   Timestamp: {datetime.now().isoformat()}")
    logger.info("=" * 70)
    logger.info("")
    
    # Import forced cleanup engine
    try:
        from forced_position_cleanup import ForcedPositionCleanup
    except ImportError:
        logger.error("❌ Failed to import forced_position_cleanup module")
        logger.error("   Make sure you're running from the repository root")
        return 1
    
    # Import multi-account manager
    try:
        from multi_account_broker_manager import multi_account_broker_manager
    except ImportError:
        logger.error("❌ Failed to import multi_account_broker_manager")
        logger.error("   Multi-account support not available")
        multi_account_broker_manager = None
    
    # Initialize cleanup engine
    cleanup = ForcedPositionCleanup(
        dust_threshold_usd=args.dust,
        max_positions=args.max_positions,
        dry_run=args.dry_run
    )
    
    # Confirmation prompt (unless --yes or --dry-run)
    if not args.dry_run and not args.yes:
        logger.warning("")
        logger.warning("⚠️  WARNING: This will execute REAL trades on live exchanges!")
        logger.warning("   Positions will be CLOSED and converted to USD/stablecoins")
        logger.warning("")
        response = input("Continue? (yes/no): ").strip().lower()
        if response not in ['yes', 'y']:
            logger.info("❌ Cleanup cancelled by user")
            return 0
        logger.info("")
    
    # Execute cleanup
    try:
        if multi_account_broker_manager:
            # Multi-account cleanup
            logger.info("🌐 Running multi-account cleanup...")
            summary = cleanup.cleanup_all_accounts(multi_account_broker_manager)
            
            logger.info("")
            logger.info("=" * 70)
            logger.info("📊 FINAL SUMMARY")
            logger.info("=" * 70)
            logger.info(f"   Accounts processed: {summary['accounts_processed']}")
            logger.info(f"   Initial total positions: {summary['initial_total']}")
            logger.info(f"   Dust positions closed: {summary['dust_closed']}")
            logger.info(f"   Cap excess closed: {summary['cap_closed']}")
            logger.info(f"   Final total positions: {summary['final_total']}")
            logger.info(f"   Total reduction: {summary['reduction']}")
            logger.info("=" * 70)
            logger.info("")
            
            if args.dry_run:
                logger.info("ℹ️  This was a DRY RUN - no trades were executed")
                logger.info("   Remove --dry-run to execute for real")
            else:
                logger.info("✅ CLEANUP COMPLETE")
                logger.info("   All positions have been processed")
            
        else:
            # Single account fallback
            logger.warning("⚠️  Multi-account manager not available")
            logger.warning("   Falling back to single-account mode")
            
            # Try to get platform broker
            try:
                from broker_manager import BrokerManager, BrokerType
                broker_mgr = BrokerManager()
                
                # Try Coinbase first
                from bot.broker_integration import CoinbaseBroker
                broker = CoinbaseBroker()
                if broker.connect():
                    result = cleanup.cleanup_single_account(broker, "platform_coinbase")
                    logger.info("")
                    logger.info("=" * 70)
                    logger.info("📊 FINAL SUMMARY")
                    logger.info("=" * 70)
                    logger.info(f"   Account: {result['account_id']}")
                    logger.info(f"   Initial positions: {result['initial_positions']}")
                    logger.info(f"   Dust closed: {result['dust_closed']}")
                    logger.info(f"   Cap excess closed: {result['cap_closed']}")
                    logger.info(f"   Final positions: {result['final_positions']}")
                    logger.info("=" * 70)
                    logger.info("")
                else:
                    logger.error("❌ Failed to connect to broker")
                    return 1
                    
            except Exception as broker_err:
                logger.error(f"❌ Failed to initialize broker: {broker_err}")
                return 1
        
        return 0
        
    except Exception as e:
        logger.error("")
        logger.error("=" * 70)
        logger.error("❌ CLEANUP FAILED")
        logger.error("=" * 70)
        logger.error(f"   Error: {e}")
        logger.error("=" * 70)
        logger.error("")
        
        import traceback
        logger.error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
