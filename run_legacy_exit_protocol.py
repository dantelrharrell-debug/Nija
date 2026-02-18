#!/usr/bin/env python3
"""
Legacy Position Exit Protocol - Command Line Interface
=======================================================

Run the 4-phase legacy position exit protocol from command line.

Usage:
    # Quick verification (no changes)
    python run_legacy_exit_protocol.py --verify-only
    
    # Full cleanup (platform first)
    python run_legacy_exit_protocol.py --broker coinbase
    
    # Dry run (log actions without executing)
    python run_legacy_exit_protocol.py --dry-run
    
    # Run specific phase only
    python run_legacy_exit_protocol.py --phase 2  # Order cleanup only
    
    # User background mode
    python run_legacy_exit_protocol.py --mode user-background --user-id USER123

Options:
    --broker BROKER        Broker name (coinbase, kraken, binance)
    --verify-only          Run verification only (Phase 4)
    --dry-run             Log actions without executing
    --phase N             Run specific phase only (1-4)
    --mode MODE           Execution mode (platform-first, user-background, full)
    --user-id ID          User account ID (for user-background mode)
    --account-id ID       Account ID to clean
"""

import argparse
import logging
import sys
import json
from datetime import datetime
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("nija.legacy_exit_cli")


def setup_broker_integration(broker_name: str):
    """
    Setup broker integration.
    
    Args:
        broker_name: Name of broker (coinbase, kraken, binance)
        
    Returns:
        Broker integration instance
    """
    try:
        from bot.broker_integration import get_broker
        broker = get_broker(broker_name)
        logger.info(f"✅ Connected to {broker_name}")
        return broker
    except ImportError as e:
        logger.error(f"Failed to import broker integration: {e}")
        logger.error("Make sure you're running from the repository root")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to connect to broker: {e}")
        sys.exit(1)


def run_verification_only(protocol):
    """Run verification only (Phase 4)"""
    logger.info("=" * 80)
    logger.info("VERIFICATION ONLY MODE")
    logger.info("=" * 80)
    
    state = protocol.verify_only()
    metrics = protocol.get_metrics()
    
    print("\n" + "=" * 80)
    print("VERIFICATION RESULTS")
    print("=" * 80)
    print(f"Account State: {state.value}")
    print(f"Positions Remaining: {metrics.positions_remaining}")
    print(f"Zombie Count: {metrics.zombie_count}")
    print(f"Cleanup Progress: {metrics.cleanup_progress_pct:.1f}%")
    print(f"Capital Freed (Total): ${metrics.capital_freed_usd:.2f}")
    print("=" * 80)
    
    return state.value == "CLEAN"


def run_specific_phase(protocol, phase: int, account_id=None):
    """Run a specific phase only"""
    logger.info(f"=" * 80)
    logger.info(f"RUNNING PHASE {phase} ONLY")
    logger.info(f"=" * 80)
    
    if phase == 1:
        classified = protocol.phase1_classify_positions(account_id)
        print("\n" + "=" * 80)
        print("PHASE 1 RESULTS: POSITION CLASSIFICATION")
        print("=" * 80)
        print(f"Strategy-Aligned: {len(classified['strategy_aligned'])}")
        print(f"Legacy Non-Compliant: {len(classified['legacy_non_compliant'])}")
        print(f"Zombie: {len(classified['zombie'])}")
        print("=" * 80)
        
    elif phase == 2:
        orders_cancelled, capital_freed = protocol.phase2_order_cleanup(account_id)
        print("\n" + "=" * 80)
        print("PHASE 2 RESULTS: ORDER CLEANUP")
        print("=" * 80)
        print(f"Orders Cancelled: {orders_cancelled}")
        print(f"Capital Freed: ${capital_freed:.2f}")
        print("=" * 80)
        
    elif phase == 3:
        # Need classification first
        classified = protocol.phase1_classify_positions(account_id)
        exits = protocol.phase3_controlled_exit(classified, account_id)
        print("\n" + "=" * 80)
        print("PHASE 3 RESULTS: CONTROLLED EXIT")
        print("=" * 80)
        print(f"Dust Closed: {exits['dust_closed']}")
        print(f"Over-Cap Closed: {exits['over_cap_closed']}")
        print(f"Legacy Unwound: {exits['legacy_unwound']}")
        print(f"Zombie Closed: {exits['zombie_closed']}")
        print("=" * 80)
        
    elif phase == 4:
        state = protocol.phase4_verify_clean_state(account_id)
        print("\n" + "=" * 80)
        print("PHASE 4 RESULTS: VERIFICATION")
        print("=" * 80)
        print(f"Account State: {state.value}")
        print("=" * 80)
    
    else:
        logger.error(f"Invalid phase: {phase}. Must be 1-4.")
        sys.exit(1)


def run_full_protocol(protocol, account_id=None):
    """Run all 4 phases"""
    results = protocol.run_full_protocol(account_id)
    
    print("\n" + "=" * 80)
    print("FULL PROTOCOL RESULTS")
    print("=" * 80)
    print(f"Account: {results['account_id']}")
    print(f"Execution Mode: {results['execution_mode']}")
    print(f"Elapsed Time: {results['elapsed_seconds']:.2f}s")
    print()
    print("PHASE 1 (Classification):")
    print(f"  Strategy-Aligned: {results['phases']['phase1']['strategy_aligned']}")
    print(f"  Legacy Non-Compliant: {results['phases']['phase1']['legacy_non_compliant']}")
    print(f"  Zombie: {results['phases']['phase1']['zombie']}")
    print()
    print("PHASE 2 (Order Cleanup):")
    print(f"  Orders Cancelled: {results['phases']['phase2']['orders_cancelled']}")
    print(f"  Capital Freed: ${results['phases']['phase2']['capital_freed_usd']:.2f}")
    print()
    print("PHASE 3 (Controlled Exit):")
    print(f"  Dust Closed: {results['phases']['phase3']['dust_closed']}")
    print(f"  Over-Cap Closed: {results['phases']['phase3']['over_cap_closed']}")
    print(f"  Legacy Unwound: {results['phases']['phase3']['legacy_unwound']}")
    print(f"  Zombie Closed: {results['phases']['phase3']['zombie_closed']}")
    print()
    print("PHASE 4 (Verification):")
    print(f"  State: {results['phases']['phase4']['state']}")
    print(f"  Positions Remaining: {results['phases']['phase4']['positions_remaining']}")
    print(f"  Zombie Count: {results['phases']['phase4']['zombie_count']}")
    print()
    print("TOTAL METRICS:")
    print(f"  Total Positions Cleaned: {results['metrics']['total_positions_cleaned']}")
    print(f"  Zombie Positions Closed: {results['metrics']['zombie_positions_closed']}")
    print(f"  Legacy Positions Unwound: {results['metrics']['legacy_positions_unwound']}")
    print(f"  Stale Orders Cancelled: {results['metrics']['stale_orders_cancelled']}")
    print(f"  Capital Freed: ${results['metrics']['capital_freed_usd']:.2f}")
    print(f"  Cleanup Progress: {results['metrics']['cleanup_progress_pct']:.1f}%")
    print("=" * 80)
    
    # Save results to file
    results_dir = Path("./data")
    results_dir.mkdir(exist_ok=True)
    
    results_file = results_dir / f"legacy_exit_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n📄 Results saved to: {results_file}")
    
    return results['state'] == "CLEAN"


def main():
    parser = argparse.ArgumentParser(
        description='Legacy Position Exit Protocol CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick verification
  python run_legacy_exit_protocol.py --verify-only
  
  # Full cleanup with Coinbase
  python run_legacy_exit_protocol.py --broker coinbase
  
  # Dry run (no actual trades)
  python run_legacy_exit_protocol.py --dry-run --broker coinbase
  
  # Run order cleanup only
  python run_legacy_exit_protocol.py --phase 2 --broker coinbase
  
  # Platform-first mode
  python run_legacy_exit_protocol.py --mode platform-first --broker coinbase
        """
    )
    
    parser.add_argument('--broker', type=str, default='coinbase',
                       help='Broker name (coinbase, kraken, binance)')
    parser.add_argument('--verify-only', action='store_true',
                       help='Run verification only (no changes)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Log actions without executing')
    parser.add_argument('--phase', type=int, choices=[1, 2, 3, 4],
                       help='Run specific phase only (1-4)')
    parser.add_argument('--mode', type=str, 
                       choices=['platform-first', 'user-background', 'full'],
                       default='platform-first',
                       help='Execution mode')
    parser.add_argument('--user-id', type=str,
                       help='User account ID (for user-background mode)')
    parser.add_argument('--account-id', type=str,
                       help='Account ID to clean')
    parser.add_argument('--dust-threshold-pct', type=float, default=0.01,
                       help='Dust threshold as percentage of account balance (default: 0.01 = 1%%)')
    parser.add_argument('--max-positions', type=int, default=8,
                       help='Maximum allowed positions (default: 8)')
    
    args = parser.parse_args()
    
    # Print header
    print("=" * 80)
    print("LEGACY POSITION EXIT PROTOCOL")
    print("=" * 80)
    print(f"Broker: {args.broker}")
    print(f"Mode: {args.mode}")
    print(f"Dry Run: {args.dry_run}")
    if args.verify_only:
        print("Mode: VERIFICATION ONLY")
    elif args.phase:
        print(f"Mode: PHASE {args.phase} ONLY")
    else:
        print("Mode: FULL PROTOCOL")
    print("=" * 80)
    print()
    
    # Setup broker
    broker = setup_broker_integration(args.broker)
    
    # Import protocol
    try:
        from bot.legacy_position_exit_protocol import (
            LegacyPositionExitProtocol, ExecutionMode
        )
    except ImportError:
        logger.error("Failed to import LegacyPositionExitProtocol")
        logger.error("Make sure you're running from the repository root")
        sys.exit(1)
    
    # Map mode string to enum
    mode_map = {
        'platform-first': ExecutionMode.PLATFORM_FIRST,
        'user-background': ExecutionMode.USER_BACKGROUND,
        'full': ExecutionMode.FULL
    }
    execution_mode = mode_map[args.mode]
    
    # Initialize protocol
    protocol = LegacyPositionExitProtocol(
        broker_integration=broker,
        dust_threshold_pct=args.dust_threshold_pct,
        max_positions=args.max_positions,
        dry_run=args.dry_run,
        execution_mode=execution_mode
    )
    
    # Determine account_id
    account_id = args.account_id or args.user_id
    
    # Execute
    try:
        if args.verify_only:
            success = run_verification_only(protocol)
        elif args.phase:
            run_specific_phase(protocol, args.phase, account_id)
            success = True
        else:
            success = run_full_protocol(protocol, account_id)
        
        if success:
            logger.info("✅ Protocol completed successfully")
            sys.exit(0)
        else:
            logger.warning("⚠️  Protocol completed with warnings")
            sys.exit(0)
            
    except KeyboardInterrupt:
        logger.info("\n⚠️  Protocol interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Protocol failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
