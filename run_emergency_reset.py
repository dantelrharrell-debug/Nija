#!/usr/bin/env python3
"""
NIJA Emergency Reset - CLI Tool

Performs a complete ordered shutdown of the NIJA trading bot:

    1. Stop the bot       (activate kill switch)
    2. Cancel open orders (all pending orders on all brokers)
    3. Liquidate          (force-sell every open position)
    4. Sweep dust         (close sub-threshold remnants)
    5. Delete state files (positions.json, open_positions.json)

Usage
-----
    python run_emergency_reset.py              # prompts for confirmation
    python run_emergency_reset.py --yes        # skip confirmation
    python run_emergency_reset.py --no-broker  # skip broker steps (kill + files only)
    python run_emergency_reset.py --dust 0.50  # custom dust threshold
    python run_emergency_reset.py --help       # show full help

WARNING
-------
This will execute REAL market orders on live exchanges.
Run with --no-broker if you only want to stop the bot and clear local state.
"""

import os
import sys
import logging
import argparse
from datetime import datetime, timezone

# Ensure the repository root and bot/ directory are on the Python path
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, 'bot'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger("nija.emergency_reset_cli")


def _build_brokers() -> list:
    """
    Attempt to construct and connect the platform brokers.

    Returns a list of connected broker instances; empty list on failure.
    """
    brokers = []

    # ── Coinbase ──────────────────────────────────────────────────────────
    try:
        try:
            from bot.broker_manager import CoinbaseBroker
        except ImportError:
            from broker_manager import CoinbaseBroker

        cb = CoinbaseBroker()
        if cb.connect():
            brokers.append(cb)
            logger.info("✅ Coinbase broker connected")
        else:
            logger.warning("⚠️  Coinbase broker failed to connect")
    except Exception as e:
        logger.warning(f"⚠️  Coinbase broker unavailable: {e}")

    # ── Kraken ────────────────────────────────────────────────────────────
    try:
        try:
            from bot.broker_manager import KrakenBroker
        except ImportError:
            from broker_manager import KrakenBroker

        kraken = KrakenBroker()
        if kraken.connect():
            brokers.append(kraken)
            logger.info("✅ Kraken broker connected")
        else:
            logger.warning("⚠️  Kraken broker failed to connect")
    except Exception as e:
        logger.warning(f"⚠️  Kraken broker unavailable: {e}")

    return brokers


def main() -> int:
    parser = argparse.ArgumentParser(
        description='NIJA Emergency Reset — stop bot, cancel orders, liquidate, sweep dust, delete state',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_emergency_reset.py                # full reset with confirmation
  python run_emergency_reset.py --yes          # full reset, no prompt
  python run_emergency_reset.py --no-broker    # kill switch + delete files only
  python run_emergency_reset.py --dust 0.50    # custom $0.50 dust threshold

Steps executed (in order):
  1. Stop the bot        — activate the global kill switch
  2. Cancel open orders  — cancel every open order on every broker
  3. Liquidate           — force-sell all positions via market orders
  4. Sweep dust          — close remaining sub-threshold positions
  5. Delete state files  — remove positions.json / open_positions.json
        """,
    )

    parser.add_argument(
        '--yes', '-y',
        action='store_true',
        help='Skip confirmation prompt (auto-confirm)',
    )
    parser.add_argument(
        '--no-broker',
        action='store_true',
        help='Skip broker-dependent steps (2–4); only activate kill switch and delete files',
    )
    parser.add_argument(
        '--dust',
        type=float,
        default=1.00,
        metavar='USD',
        help='Dust threshold in USD (default: 1.00)',
    )
    parser.add_argument(
        '--reason',
        type=str,
        default='Emergency reset via CLI',
        help='Reason recorded in kill-switch log (default: "Emergency reset via CLI")',
    )

    args = parser.parse_args()

    # ── Banner ────────────────────────────────────────────────────────────
    logger.warning("")
    logger.warning("=" * 70)
    logger.warning("🚨 NIJA EMERGENCY RESET")
    logger.warning("=" * 70)
    logger.warning(f"   Timestamp  : {datetime.now(timezone.utc).isoformat()}")
    logger.warning(f"   Broker ops : {'DISABLED (--no-broker)' if args.no_broker else 'ENABLED'}")
    logger.warning(f"   Dust limit : ${args.dust:.2f}")
    logger.warning("=" * 70)
    logger.warning("")

    # ── Confirmation ──────────────────────────────────────────────────────
    if not args.yes:
        logger.warning("⚠️  WARNING: This will execute REAL trades on live exchanges!")
        logger.warning("   All open orders will be cancelled.")
        logger.warning("   All positions will be force-sold at market price.")
        logger.warning("   Position tracking files will be permanently deleted.")
        logger.warning("")
        response = input("Type 'yes' to continue, anything else to abort: ").strip().lower()
        if response != 'yes':
            logger.info("❌ Reset aborted by user")
            return 0
        logger.warning("")

    # ── Import the reset module ───────────────────────────────────────────
    try:
        try:
            from bot.emergency_reset import run_emergency_reset
        except ImportError:
            from emergency_reset import run_emergency_reset
    except ImportError as e:
        logger.error(f"❌ Could not import emergency_reset module: {e}")
        return 1

    # ── Build broker list ─────────────────────────────────────────────────
    brokers = []
    if not args.no_broker:
        logger.info("🔌 Connecting to brokers…")
        brokers = _build_brokers()
        if not brokers:
            logger.warning("⚠️  No brokers connected — broker steps will be skipped")

    # ── Execute reset ─────────────────────────────────────────────────────
    try:
        summary = run_emergency_reset(
            brokers=brokers,
            dust_threshold_usd=args.dust,
            stop_reason=args.reason,
        )
    except Exception as e:
        logger.error(f"❌ Emergency reset failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # ── Exit code: non-zero if kill switch failed ─────────────────────────
    if not summary.get('kill_switch_activated', False):
        logger.error("❌ Kill switch was NOT activated — review logs above")
        return 1

    logger.info("✅ Emergency reset completed successfully")
    return 0


if __name__ == '__main__':
    sys.exit(main())
