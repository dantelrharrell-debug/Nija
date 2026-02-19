#!/usr/bin/env python3
"""
Run Legacy Position Exit Protocol
Backward-compatible CLI that works with both legacy and new protocol APIs.
"""

import argparse
import inspect
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("nija.legacy_exit_cli")


def get_broker_adapter(broker_name: str, dry_run: bool = False):
    try:
        from bot.broker_integration import get_broker as _get_broker

        return _get_broker(broker_name)
    except Exception:
        try:
            from bot.broker_integration import get_broker_integration as _get_broker_integration

            return _get_broker_integration(broker_name, dry_run=dry_run)
        except Exception as exc:
            logger.error(f"Failed to initialize broker integration: {exc}")
            raise


def get_protocol_classes():
    from bot.legacy_position_exit_protocol import LegacyPositionExitProtocol

    execution_mode = None
    account_state = None

    try:
        from bot.legacy_position_exit_protocol import ExecutionMode as _execution_mode

        execution_mode = _execution_mode
    except Exception:
        execution_mode = None

    try:
        from bot.legacy_position_exit_protocol import AccountState as _account_state

        account_state = _account_state
    except Exception:
        account_state = None

    return LegacyPositionExitProtocol, execution_mode, account_state


def build_protocol(args, broker, protocol_cls, execution_mode_cls):
    sig = inspect.signature(protocol_cls.__init__)
    params = sig.parameters

    kwargs = {"broker_integration": broker}

    if "position_tracker" in params:
        try:
            from bot.position_tracker import PositionTracker

            kwargs["position_tracker"] = PositionTracker(storage_file="data/positions.json")
        except Exception as exc:
            logger.warning(f"PositionTracker unavailable, continuing without it: {exc}")

    if "max_positions" in params:
        kwargs["max_positions"] = args.max_positions

    if "dust_threshold_pct" in params:
        kwargs["dust_threshold_pct"] = args.dust_threshold_pct
    if "dust_pct_threshold" in params:
        kwargs["dust_pct_threshold"] = args.dust_threshold_pct

    if "stale_order_minutes" in params:
        kwargs["stale_order_minutes"] = args.stale_minutes

    if "dry_run" in params:
        kwargs["dry_run"] = args.dry_run

    if "data_dir" in params:
        kwargs["data_dir"] = "./data"

    if execution_mode_cls and "execution_mode" in params:
        mode_map = {
            "platform-first": execution_mode_cls.PLATFORM_FIRST,
            "user-background": execution_mode_cls.USER_BACKGROUND,
            "full": execution_mode_cls.FULL,
        }
        kwargs["execution_mode"] = mode_map[args.mode]

    return protocol_cls(**kwargs)


def normalize_state_value(state):
    if hasattr(state, "value"):
        return state.value
    return str(state)


def verify_only(protocol, account_id):
    if hasattr(protocol, "verify_only"):
        state = protocol.verify_only(account_id) if account_id else protocol.verify_only()
        return normalize_state_value(state)

    state, _diagnostics = protocol.verify_clean_state(user_id=account_id)
    return normalize_state_value(state)


def run_phase(protocol, phase: int, account_id, broker):
    if hasattr(protocol, "phase1_classify_positions"):
        if phase == 1:
            result = protocol.phase1_classify_positions(account_id)
            logger.info(f"Phase 1 complete: {len(result.get('strategy_aligned', []))} strategy-aligned")
            return True
        if phase == 2:
            cancelled, freed = protocol.phase2_order_cleanup(account_id)
            logger.info(f"Phase 2 complete: cancelled={cancelled}, freed=${freed:.2f}")
            return True
        if phase == 3:
            classified = protocol.phase1_classify_positions(account_id)
            result = protocol.phase3_controlled_exit(classified, account_id)
            logger.info(f"Phase 3 complete: processed={sum(result.values()) if result else 0}")
            return True
        if phase == 4:
            state = protocol.phase4_verify_clean_state(account_id)
            logger.info(f"Phase 4 complete: state={normalize_state_value(state)}")
            return True
        return False

    positions = broker.get_open_positions(user_id=account_id)
    balance = broker.get_account_balance(user_id=account_id)

    if phase == 1:
        classified = protocol.classify_all_positions(positions, balance)
        logger.info(f"Phase 1 complete: classified={len(classified)}")
        return True
    if phase == 2:
        cancelled, freed = protocol.cancel_stale_orders(user_id=account_id)
        logger.info(f"Phase 2 complete: cancelled={cancelled}, freed=${freed:.2f}")
        return True
    if phase == 3:
        classified = protocol.classify_all_positions(positions, balance)
        result = protocol.execute_controlled_exits(classified, balance)
        successful = sum(1 for v in result.values() if v)
        logger.info(f"Phase 3 complete: successful={successful}/{len(result)}")
        return True
    if phase == 4:
        state, _diagnostics = protocol.verify_clean_state(user_id=account_id)
        logger.info(f"Phase 4 complete: state={normalize_state_value(state)}")
        return True

    return False


def run_full(protocol, account_id):
    results = protocol.run_full_protocol(account_id) if account_id else protocol.run_full_protocol()

    data_dir = Path("./data")
    data_dir.mkdir(exist_ok=True)
    result_file = data_dir / f"legacy_exit_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    with open(result_file, "w") as handle:
        json.dump(results, handle, indent=2, default=str)

    logger.info(f"Results saved to {result_file}")

    if isinstance(results, dict):
        if "state" in results:
            return str(results["state"]).upper() == "CLEAN"
        if "success" in results:
            return bool(results["success"])

    return True


def main():
    parser = argparse.ArgumentParser(description="Run Legacy Position Exit Protocol")

    parser.add_argument("--broker", default="coinbase", help="Broker name")
    parser.add_argument("--max-positions", type=int, default=8, help="Maximum positions")
    parser.add_argument("--dust-pct", type=float, default=0.01, help="Dust threshold ratio (legacy arg)")
    parser.add_argument(
        "--dust-threshold-pct",
        type=float,
        default=None,
        help="Dust threshold ratio (new arg)",
    )
    parser.add_argument("--stale-minutes", type=int, default=30, help="Stale order age in minutes")
    parser.add_argument("--user-id", type=str, default=None, help="User account ID")
    parser.add_argument("--account-id", type=str, default=None, help="Account ID")
    parser.add_argument("--dry-run", action="store_true", help="Simulate actions")
    parser.add_argument("--verify-only", action="store_true", help="Run verification only")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3, 4], help="Run one phase")
    parser.add_argument(
        "--mode",
        choices=["platform-first", "user-background", "full"],
        default="platform-first",
        help="Execution mode for new protocol API",
    )

    args = parser.parse_args()
    args.dust_threshold_pct = args.dust_threshold_pct if args.dust_threshold_pct is not None else args.dust_pct

    account_id = args.account_id or args.user_id

    logger.info("=" * 80)
    logger.info("LEGACY POSITION EXIT PROTOCOL")
    logger.info("=" * 80)
    logger.info(f"Broker: {args.broker}")
    logger.info(f"Dry Run: {args.dry_run}")
    logger.info(f"Mode: {args.mode}")

    try:
        protocol_cls, execution_mode_cls, account_state_cls = get_protocol_classes()
        broker = get_broker_adapter(args.broker, dry_run=args.dry_run)
        protocol = build_protocol(args, broker, protocol_cls, execution_mode_cls)

        if args.verify_only:
            state_value = verify_only(protocol, account_id)
            logger.info(f"Verification state: {state_value}")
            clean_value = "CLEAN"
            if account_state_cls and hasattr(account_state_cls, "CLEAN"):
                clean_value = normalize_state_value(account_state_cls.CLEAN)
            return 0 if state_value == clean_value else 1

        if args.phase:
            ok = run_phase(protocol, args.phase, account_id, broker)
            return 0 if ok else 1

        success = run_full(protocol, account_id)
        return 0 if success else 1

    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 1
    except Exception as exc:
        logger.error(f"Protocol execution failed: {exc}")
        import traceback

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


if __name__ == "__main__":
if __name__ == '__main__':
    sys.exit(main())
