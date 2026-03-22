#!/usr/bin/env python3
"""
Clean Kraken All Accounts
=========================

Multi-account variant of clean_kraken.py.

Finds every Kraken credential set in the environment (platform + numbered user
slots) and runs the full cleanup sequence on each account:

    1. Cancel all open orders
    2. Force-sell all positions above Kraken's $10 minimum
    3. Sweep dust (convert sub-minimum balances to USD)
    4. Verify cleanup
    5. Report ideal-state

After processing all accounts:
    6. Delete positions.json / open_positions.json (reset persisted state)

Ideal-state logic (updated — $200 upper cap removed):
    ✅ IDEAL  =  usd_balance >= $50  AND  positions <= 3

Usage:
    python scripts/clean_kraken_all_accounts.py [--dry-run]

Options:
    --dry-run    Show what would be done without executing any trades

Requirements:
    Set at least one of the following in your environment:
        KRAKEN_PLATFORM_API_KEY + KRAKEN_PLATFORM_API_SECRET
        KRAKEN_API_KEY + KRAKEN_API_SECRET
        KRAKEN_USER1_API_KEY + KRAKEN_USER1_API_SECRET  (and so on up to USER9)

Author: NIJA Trading Bot
Date: 2026-03-22
"""

import os
import sys
import argparse
import time
from typing import Dict, List, Optional
from datetime import datetime

# Add bot directory to path so we can import broker modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bot'))

from broker_integration import KrakenBrokerAdapter

# Re-use single-account helpers from clean_kraken.py
sys.path.insert(0, os.path.dirname(__file__))
from clean_kraken import (
    print_banner,
    cancel_all_orders,
    force_sell_all_positions,
    sweep_dust_positions,
    get_all_crypto_balances,
    verify_cleanup,
)

# ── Ideal-state thresholds ────────────────────────────────────────────────────

DUST_THRESHOLD_USD = 1.00   # Positions below this are considered dust
IDEAL_MIN_USD = 50.0        # Minimum USD cash balance for ideal state
IDEAL_MAX_POSITIONS = 3     # Maximum open positions allowed for ideal state
# NOTE: The previous $200 upper cap (IDEAL_MAX_USD) has been intentionally
#       removed.  Ideal state is now: usd_balance >= $50 AND positions <= 3.


# ── Helpers ───────────────────────────────────────────────────────────────────

def _delete_position_files(extra_paths: Optional[List[str]] = None) -> List[str]:
    """
    Delete positions.json and related position-tracking files.

    Tries to import the canonical helper from emergency_reset; falls back to
    an inline implementation so this script remains fully self-contained.

    Args:
        extra_paths: Additional file paths to delete.

    Returns:
        List of file paths that were successfully deleted.
    """
    try:
        try:
            from bot.emergency_reset import delete_position_files
        except ImportError:
            from emergency_reset import delete_position_files
        return delete_position_files(extra_paths)
    except ImportError:
        pass

    # Inline fallback
    candidates = [
        "positions.json",
        "data/positions.json",
        "data/open_positions.json",
        "bot/data/positions.json",
        "bot/data/open_positions.json",
    ]
    if extra_paths:
        candidates.extend(extra_paths)

    deleted: List[str] = []
    for path in candidates:
        abs_path = os.path.abspath(path)
        if os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
                print(f"🗑️  Deleted: {abs_path}")
                deleted.append(abs_path)
            except Exception as exc:
                print(f"⚠️  Could not delete {abs_path}: {exc}")
    return deleted


def _get_usd_cash(adapter: KrakenBrokerAdapter) -> float:
    """Return the USD/USDT cash balance for this account."""
    try:
        result = adapter._kraken_api_call('Balance')
        if not result or 'result' not in result:
            return 0.0
        balances = result['result']
        return float(
            balances.get('ZUSD',
            balances.get('USD',
            balances.get('USDT', 0)))
        )
    except Exception as exc:
        print(f"⚠️  Could not fetch USD cash balance: {exc}")
        return 0.0


# ── Core functions ─────────────────────────────────────────────────────────────

def check_ideal_state(adapter: KrakenBrokerAdapter, account_name: str) -> Dict:
    """
    Evaluate the account against the ideal-state targets and print a report.

    Ideal state (updated — $200 upper cap removed):
        • positions <= 3
        • usd_balance >= $50  (no upper limit)
        • no dust clutter (holdings < $1)

    Args:
        adapter:      Connected KrakenBrokerAdapter instance.
        account_name: Human-readable label used in the report.

    Returns:
        Dict with keys: account, status, positions, usd_balance, dust_count,
        positions_ok, usd_ok, dust_ok, all_ok.
    """
    print_banner(f"IDEAL STATE CHECK — {account_name}")

    usd_balance = _get_usd_cash(adapter)
    balances = get_all_crypto_balances(adapter)

    sig_positions = [b for b in balances if b['usd_value'] >= DUST_THRESHOLD_USD]
    dust_positions = [b for b in balances if b['usd_value'] < DUST_THRESHOLD_USD]
    position_count = len(sig_positions)

    positions_ok = position_count <= IDEAL_MAX_POSITIONS
    # Updated: only enforce the lower bound — no upper cap on USD balance
    usd_ok = usd_balance >= IDEAL_MIN_USD
    dust_ok = len(dust_positions) == 0

    pos_icon = "✅" if positions_ok else "⚠️ "
    usd_icon = "✅" if usd_ok else "⚠️ "
    dust_icon = "✅" if dust_ok else "⚠️ "

    print(f"{pos_icon} Positions   : {position_count} (target: ≤ {IDEAL_MAX_POSITIONS})")
    for bal in sig_positions:
        print(f"      • {bal['currency']}: ${bal['usd_value']:.2f}")

    print(f"{usd_icon} USD balance : ${usd_balance:.2f} (target: ≥ ${IDEAL_MIN_USD:.0f})")

    print(f"{dust_icon} Dust clutter: {len(dust_positions)} item(s) (target: 0)")
    for bal in dust_positions:
        print(f"      • {bal['currency']}: ${bal['usd_value']:.4f} (< $1 — ignored)")

    all_ok = positions_ok and usd_ok and dust_ok
    if all_ok:
        status = "✅ IDEAL"
    else:
        status = "⚠️  NOT YET IDEAL"

    print(f"\n{'=' * 40}")
    print(f"  {status}")
    print(f"{'=' * 40}")

    return {
        'account': account_name,
        'status': status,
        'positions': position_count,
        'usd_balance': usd_balance,
        'dust_count': len(dust_positions),
        'positions_ok': positions_ok,
        'usd_ok': usd_ok,
        'dust_ok': dust_ok,
        'all_ok': all_ok,
    }


def _discover_accounts() -> List[Dict]:
    """
    Discover all Kraken API credential sets from the environment.

    Checks, in order:
        • KRAKEN_PLATFORM_API_KEY / KRAKEN_PLATFORM_API_SECRET  → "platform"
        • KRAKEN_API_KEY / KRAKEN_API_SECRET                    → "platform" (fallback)
        • KRAKEN_USER{N}_API_KEY / KRAKEN_USER{N}_API_SECRET    → "user{N}" for N=1..9

    Returns:
        List of dicts with keys: name, key, secret.
    """
    accounts: List[Dict] = []

    # Platform account
    key = os.getenv('KRAKEN_PLATFORM_API_KEY') or os.getenv('KRAKEN_API_KEY')
    secret = os.getenv('KRAKEN_PLATFORM_API_SECRET') or os.getenv('KRAKEN_API_SECRET')
    if key and secret:
        accounts.append({'name': 'platform', 'key': key, 'secret': secret})

    # Numbered user accounts
    for n in range(1, 10):
        k = os.getenv(f'KRAKEN_USER{n}_API_KEY')
        s = os.getenv(f'KRAKEN_USER{n}_API_SECRET')
        if k and s:
            accounts.append({'name': f'user{n}', 'key': k, 'secret': s})

    return accounts


def run_clean_kraken_all_accounts(dry_run: bool = False) -> Dict:
    """
    Run the full cleanup sequence across ALL Kraken accounts, then reset the
    persisted position-tracking state.

    Steps per account:
        1. Cancel all open orders
        2. Force-sell all positions above Kraken's minimum order cost
        3. Sweep remaining dust positions
        4. Verify cleanup
        5. Report ideal-state check

    After all accounts:
        6. Delete positions.json / open_positions.json

    Args:
        dry_run: When True, preview every action without executing any trades
                 or deleting any files.

    Returns:
        Summary dict with keys: accounts_processed, results, files_deleted,
        completed_at.
    """
    print_banner(
        "KRAKEN ALL-ACCOUNTS CLEANUP" + (" [DRY RUN]" if dry_run else "")
    )

    accounts = _discover_accounts()
    if not accounts:
        print(
            "❌ No Kraken API credentials found in environment.\n"
            "   Set KRAKEN_PLATFORM_API_KEY + KRAKEN_PLATFORM_API_SECRET\n"
            "   (or KRAKEN_API_KEY + KRAKEN_API_SECRET)."
        )
        return {'accounts_processed': 0, 'results': [], 'files_deleted': [], 'completed_at': datetime.now().isoformat()}

    print(f"🔍 Found {len(accounts)} Kraken account(s): "
          f"{', '.join(a['name'] for a in accounts)}\n")

    results: List[Dict] = []

    for acct in accounts:
        name = acct['name']
        print_banner(f"CLEANING ACCOUNT: {name.upper()}")

        adapter = KrakenBrokerAdapter(api_key=acct['key'], api_secret=acct['secret'])
        if not adapter.connect():
            print(f"❌ Could not connect to Kraken for account '{name}' — skipping")
            results.append({'account': name, 'error': 'connection failed'})
            continue

        try:
            # Show balance before cleanup
            try:
                bi = adapter.get_account_balance()
                if not bi.get('error'):
                    print(f"💰 Balance before cleanup: ${bi.get('total_balance', 0):.2f}\n")
            except Exception:
                pass

            # Run cleanup steps
            cancel_ok, cancel_fail = cancel_all_orders(adapter, dry_run=dry_run)
            sell_ok, sell_fail, small_count = force_sell_all_positions(adapter, dry_run=dry_run)
            sweep_ok, sweep_fail = sweep_dust_positions(adapter, dry_run=dry_run)

            if not dry_run and (sell_ok > 0 or sweep_ok > 0):
                print("\n⏳ Waiting 5 seconds for orders to settle...")
                time.sleep(5)

            clean = verify_cleanup(adapter) if not dry_run else True
            ideal = check_ideal_state(adapter, name) if not dry_run else {}

            results.append({
                'account': name,
                'cancelled': cancel_ok,
                'sold': sell_ok,
                'swept': sweep_ok,
                'clean': clean,
                'ideal_state': ideal,
            })

        except Exception as exc:
            print(f"❌ Unexpected error cleaning account '{name}': {exc}")
            import traceback
            traceback.print_exc()
            results.append({'account': name, 'error': str(exc)})

    # ── Reset persisted position state ────────────────────────────────────────
    files_deleted: List[str] = []
    if not dry_run:
        print_banner("RESETTING POSITION STATE")
        files_deleted = _delete_position_files()
        if files_deleted:
            print(f"✅ Deleted {len(files_deleted)} position file(s)")
        else:
            print("ℹ️  No stale position files found")

    # ── Final summary ──────────────────────────────────────────────────────────
    print_banner("ALL-ACCOUNTS CLEANUP COMPLETE")
    for r in results:
        err = r.get('error')
        if err:
            print(f"  ⚠️  {r['account']}: ERROR — {err}")
        else:
            is_ideal = r.get('ideal_state', {}).get('all_ok', False)
            icon = "✅" if is_ideal else "⚠️ "
            print(
                f"  {icon} {r['account']}: "
                f"sold={r.get('sold', 0)}, swept={r.get('swept', 0)}, "
                f"clean={r.get('clean', False)}"
            )

    return {
        'accounts_processed': len(results),
        'results': results,
        'files_deleted': files_deleted,
        'completed_at': datetime.now().isoformat(),
    }


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Clean ALL Kraken accounts: cancel orders, sell positions, sweep dust'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without executing any trades',
    )
    args = parser.parse_args()

    summary = run_clean_kraken_all_accounts(dry_run=args.dry_run)
    sys.exit(0 if summary['accounts_processed'] > 0 else 1)


if __name__ == '__main__':
    main()
