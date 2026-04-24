#!/usr/bin/env python3
"""

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
Per-Account Kraken Cleanup
Performs a clean-slate cleanup for each Kraken account (Tania, Daivon, Platform)
and reports the TRUE balance for each account before and after cleanup.

TRUE BALANCE = USD cash + USD value of every crypto holding
(what the account is actually worth right now)

For EACH account the script runs three steps in order:
  STEP 1 — Sell anything ≥ $1.00  → Convert to USD
             • Positions ≥ $10:  standard Kraken market-sell order
             • Positions  $1–$10: Kraken ConvertFunds (no minimum)
  STEP 2 — Cancel all open orders → Unlock held funds
  STEP 3 — Leave dust alone       → Any balance < $1.00 is ignored forever

After cleanup each account is evaluated against the IDEAL STATE:
  ✅ 0–3 open positions
  ✅ $50–$200 clean USD
  ✅ No dust clutter

Usage:
    python scripts/clean_kraken_all_accounts.py [--dry-run] [--account ACCOUNT]

Options:
    --dry-run            Preview actions — no trades executed
    --account ACCOUNT    Only process one account: tania | daivon | platform
                         (default: all three accounts)

Environment variables (per account):
    KRAKEN_PLATFORM_API_KEY        KRAKEN_PLATFORM_API_SECRET
    KRAKEN_USER_DAIVON_API_KEY     KRAKEN_USER_DAIVON_API_SECRET
    KRAKEN_USER_TANIA_API_KEY      KRAKEN_USER_TANIA_API_SECRET

Author: NIJA Trading Bot
Date: 2026-03-22
"""

import os
import sys
import argparse
import time
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Path setup: allow importing from the bot/ package
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bot'))

from broker_integration import KrakenBrokerAdapter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DUST_THRESHOLD_USD = 1.00        # Below this → ignore forever (dust)
KRAKEN_MIN_ORDER_USD = 10.00     # Kraken minimum for market orders
RATE_LIMIT_SELL_SECONDS = 0.20   # Delay between sell / convert calls
RATE_LIMIT_CANCEL_SECONDS = 0.10 # Delay between order-cancel calls
SETTLE_WAIT_SECONDS = 5          # Wait after trades before verification

# Ideal-state thresholds
IDEAL_MAX_POSITIONS = 3
IDEAL_MIN_USD = 50.00
IDEAL_MAX_USD = 200.00

# ---------------------------------------------------------------------------
# Account registry
# ---------------------------------------------------------------------------
ACCOUNTS = [
    {
        "name": "Tania",
        "id": "tania",
        "key_env": "KRAKEN_USER_TANIA_API_KEY",
        "secret_env": "KRAKEN_USER_TANIA_API_SECRET",
    },
    {
        "name": "Daivon",
        "id": "daivon",
        "key_env": "KRAKEN_USER_DAIVON_API_KEY",
        "secret_env": "KRAKEN_USER_DAIVON_API_SECRET",
    },
    {
        "name": "Platform",
        "id": "platform",
        "key_env": "KRAKEN_PLATFORM_API_KEY",
        "secret_env": "KRAKEN_PLATFORM_API_SECRET",
    },
]


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_banner(message: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {message}")
    print("=" * 80 + "\n")


def print_account_header(account_name: str) -> None:
    print("\n" + "█" * 80)
    print(f"  ACCOUNT: {account_name.upper()}")
    print("█" * 80 + "\n")


# ---------------------------------------------------------------------------
# Kraken helpers (stateless — each accepts an adapter instance)
# ---------------------------------------------------------------------------

def _convert_asset_code(asset: str) -> str:
    """Map Kraken internal asset codes to standard ticker symbols."""
    if asset.startswith('X') and len(asset) == 4:
        asset = asset[1:]
    if asset == 'XBT':
        return 'BTC'
    if asset == 'XDG':
        return 'DOGE'
    return asset


def get_open_orders(adapter: KrakenBrokerAdapter) -> List[Dict]:
    """Return all open orders for the account."""
    try:
        result = adapter._kraken_api_call('OpenOrders')
        if not result or 'result' not in result:
            return []
        raw = result['result'].get('open', {})
        orders = []
        for order_id, order in raw.items():
            descr = order.get('descr', {})
            orders.append({
                'order_id': order_id,
                'pair': descr.get('pair', 'UNKNOWN'),
                'type': descr.get('type', 'UNKNOWN'),
                'ordertype': descr.get('ordertype', 'UNKNOWN'),
                'volume': float(order.get('vol', 0)),
            })
        return orders
    except Exception as exc:
        print(f"   ❌ Error fetching open orders: {exc}")
        return []


def get_crypto_balances(adapter: KrakenBrokerAdapter) -> List[Dict]:
    """
    Return all non-USD/USDT balances with their current USD valuations.
    Balances that cannot be priced are included with usd_value=0.
    """
    try:
        balance_result = adapter._kraken_api_call('Balance')
        if not balance_result or 'result' not in balance_result:
            return []

        balances = []
        for asset, amount in balance_result['result'].items():
            balance_val = float(amount)
            if asset in ('ZUSD', 'USDT', 'USD') or balance_val <= 0:
                continue

            currency = _convert_asset_code(asset)
            current_price = 0.0
            ticker_pair_used = None

            # Build candidate ticker pairs from most to least specific
            candidates: List[str] = []
            if currency == 'BTC':
                candidates = ['XXBTZUSD', 'XBTUSD', 'BTCUSD']
            elif currency == 'ETH':
                candidates = ['XETHZUSD', 'ETHUSD']
            else:
                candidates = [
                    f'{asset}USD',
                    f'{asset}ZUSD',
                    f'X{currency}ZUSD',
                    f'{currency}USD',
                ]

            for pair in candidates:
                try:
                    tick = adapter._kraken_api_call('Ticker', {'pair': pair})
                    if tick and 'result' in tick and tick['result']:
                        data = (tick['result'].get(pair)
                                or list(tick['result'].values())[0])
                        last = data.get('c', [0])[0]
                        price = float(last)
                        if price > 0:
                            current_price = price
                            ticker_pair_used = pair
                            break
                except Exception:
                    continue

            balances.append({
                'asset': asset,
                'currency': currency,
                'balance': balance_val,
                'current_price': current_price,
                'usd_value': balance_val * current_price,
                'ticker_pair': ticker_pair_used,
            })

        return balances

    except Exception as exc:
        print(f"   ❌ Error fetching balances: {exc}")
        return []


def get_usd_balance(adapter: KrakenBrokerAdapter) -> float:
    """Return the combined USD + USDT cash balance."""
    try:
        result = adapter._kraken_api_call('Balance')
        if not result or 'result' not in result:
            return 0.0
        raw = result['result']
        return float(raw.get('ZUSD', 0)) + float(raw.get('USDT', 0))
    except Exception:
        return 0.0


def get_true_balance(adapter: KrakenBrokerAdapter) -> Dict:
    """
    Compute the TRUE account balance:
        true_total = USD cash + sum(USD value of every crypto holding)

    Returns a dict:
        usd_cash     – liquid USD/USDT in the account
        crypto_value – total USD value of all crypto positions (priced only)
        true_total   – usd_cash + crypto_value
        holdings     – list of individual balance dicts from get_crypto_balances()
        unpriced     – assets whose price could not be determined
        open_orders  – list of open orders (funds locked in these are noted)
    """
    usd_cash = get_usd_balance(adapter)
    holdings = get_crypto_balances(adapter)
    orders = get_open_orders(adapter)

    priced = [h for h in holdings if h['current_price'] > 0]
    unpriced = [h for h in holdings if h['current_price'] == 0]

    crypto_value = sum(h['usd_value'] for h in priced)
    true_total = usd_cash + crypto_value

    return {
        'usd_cash': usd_cash,
        'crypto_value': crypto_value,
        'true_total': true_total,
        'holdings': holdings,
        'unpriced': unpriced,
        'open_orders': orders,
    }


def show_true_balance(tb: Dict, label: str = "") -> None:
    """
    Print a formatted true-balance snapshot.

    Args:
        tb:    Result dict from get_true_balance().
        label: Optional heading suffix, e.g. "BEFORE CLEANUP".
    """
    heading = f"TRUE BALANCE{(' — ' + label) if label else ''}"
    print(f"\n{'─' * 60}")
    print(f"  💵 {heading}")
    print(f"{'─' * 60}")
    print(f"  USD / USDT cash  : ${tb['usd_cash']:>10.2f}")

    if tb['holdings']:
        print(f"  Crypto holdings  :")
        for h in sorted(tb['holdings'], key=lambda x: x['usd_value'], reverse=True):
            if h['current_price'] > 0:
                print(f"    • {h['currency']:6s}  {h['balance']:>18.8f}"
                      f"  @  ${h['current_price']:>12.4f}  =  ${h['usd_value']:>10.2f}")
            else:
                print(f"    • {h['currency']:6s}  {h['balance']:>18.8f}"
                      f"  (price unavailable — not counted in total)")
    else:
        print(f"  Crypto holdings  : none")

    if tb['unpriced']:
        names = ', '.join(u['currency'] for u in tb['unpriced'])
        print(f"  ⚠️  Unpriced assets (excluded from total): {names}")

    if tb['open_orders']:
        print(f"  🔒 Open orders   : {len(tb['open_orders'])} "
              f"order(s) — funds may be locked until cancelled")

    print(f"{'─' * 60}")
    print(f"  TOTAL            : ${tb['true_total']:>10.2f}")
    print(f"{'─' * 60}\n")


# ---------------------------------------------------------------------------
# Step 1: Sell positions ≥ $1
# ---------------------------------------------------------------------------

def step1_sell_positions(
    adapter: KrakenBrokerAdapter,
    dry_run: bool = False,
) -> Tuple[int, int]:
    """
    Sell all holdings with USD value ≥ DUST_THRESHOLD_USD.

    Positions ≥ KRAKEN_MIN_ORDER_USD  → market sell order
    Positions  $1–$10                 → ConvertFunds (no minimum required)
    Positions  < $1                   → ignored (dust, handled by Step 3)

    Returns:
        (success_count, fail_count)
    """
    print_banner("STEP 1: Sell Anything ≥ $1.00 → Convert to USD")

    balances = get_crypto_balances(adapter)

    sellable = [b for b in balances if b['usd_value'] >= DUST_THRESHOLD_USD]
    dust = [b for b in balances if b['usd_value'] < DUST_THRESHOLD_USD]

    if not sellable and not dust:
        print("✅ No crypto balances found — nothing to sell")
        return (0, 0)

    if sellable:
        print(f"📋 Found {len(sellable)} position(s) to sell (≥ $1.00):")
        for bal in sellable:
            tag = "MARKET" if bal['usd_value'] >= KRAKEN_MIN_ORDER_USD else "CONVERT"
            print(f"   • [{tag}] {bal['currency']}: {bal['balance']:.8f}"
                  f" @ ${bal['current_price']:.4f} = ${bal['usd_value']:.2f}")
    else:
        print("✅ No positions ≥ $1.00 to sell")

    if dust:
        print(f"\n⏭️  {len(dust)} dust position(s) < $1.00 — will be ignored (Step 3):")
        for bal in dust:
            print(f"   • {bal['currency']}: {bal['balance']:.8f} = ${bal['usd_value']:.4f}")

    if dry_run:
        print(f"\n🔍 DRY RUN: Would sell {len(sellable)} position(s)")
        return (len(sellable), 0)

    success_count = fail_count = 0
    for bal in sellable:
        currency = bal['currency']
        asset = bal['asset']
        balance = bal['balance']
        usd_value = bal['usd_value']

        print(f"\n   🔴 Processing {currency}: {balance:.8f} (≈${usd_value:.2f})...")

        sold = False

        # ── Market sell for positions above Kraken's $10 minimum ─────────────
        if usd_value >= KRAKEN_MIN_ORDER_USD:
            try:
                symbol = f"{currency}-USD"
                res = adapter.place_market_order(
                    symbol=symbol,
                    side='sell',
                    size=balance,
                    size_type='base',
                )
                if res and res.get('status') not in ('error', 'skipped'):
                    order_id = str(res.get('order_id', 'N/A'))[:12]
                    print(f"      ✅ SOLD via market order (ID: {order_id}...)")
                    success_count += 1
                    sold = True
                else:
                    err = res.get('error', 'Unknown') if res else 'No response'
                    print(f"      ⚠️  Market order failed ({err}) — trying ConvertFunds…")
            except Exception as exc:
                print(f"      ⚠️  Market order raised error ({exc}) — trying ConvertFunds…")

        # ── ConvertFunds for $1–$10 positions (or market-order fallback) ─────
        if not sold:
            try:
                res = adapter._kraken_api_call('ConvertFunds', {
                    'from_asset': asset,
                    'to_asset': 'ZUSD',
                    'from_amount': str(balance),
                })
                errors = res.get('error', []) if res else ['No response']
                if res and not errors and 'result' in res:
                    ref = str(res['result'].get('order_id', 'N/A'))[:12]
                    print(f"      ✅ CONVERTED via ConvertFunds: {currency} → USD"
                          f" (ref: {ref}...)")
                    success_count += 1
                    sold = True
                else:
                    err_str = ', '.join(errors) if isinstance(errors, list) else str(errors)
                    print(f"      ❌ ConvertFunds declined ({err_str})")
                    fail_count += 1
            except Exception as exc:
                print(f"      ❌ ConvertFunds error: {exc}")
                fail_count += 1

        time.sleep(RATE_LIMIT_SELL_SECONDS)

    print(f"\n📊 Step 1 Summary: {success_count} sold/converted, {fail_count} failed")
    return (success_count, fail_count)


# ---------------------------------------------------------------------------
# Step 2: Cancel open orders
# ---------------------------------------------------------------------------

def step2_cancel_orders(
    adapter: KrakenBrokerAdapter,
    dry_run: bool = False,
) -> Tuple[int, int]:
    """
    Cancel all open orders to unlock any held funds.

    Returns:
        (success_count, fail_count)
    """
    print_banner("STEP 2: Cancel Open Orders → Unlock Held Funds")

    orders = get_open_orders(adapter)

    if not orders:
        print("✅ No open orders found — nothing to cancel")
        return (0, 0)

    print(f"📋 Found {len(orders)} open order(s):")
    for order in orders:
        short_id = order['order_id'][:12]
        print(f"   • {order['pair']}: {order['type']} {order['volume']:.8f}"
              f" ({order['ordertype']}) — ID: {short_id}...")

    if dry_run:
        print(f"\n🔍 DRY RUN: Would cancel {len(orders)} order(s)")
        return (len(orders), 0)

    print("\n🔴 Cancelling all orders...")
    success_count = fail_count = 0
    for order in orders:
        order_id = order['order_id']
        short_id = order_id[:12]
        try:
            ok = adapter.cancel_order(order_id)
            if ok:
                print(f"   ✅ Cancelled: {order['pair']} (ID: {short_id}...)")
                success_count += 1
            else:
                print(f"   ❌ Failed to cancel: {order['pair']} (ID: {short_id}...)")
                fail_count += 1
        except Exception as exc:
            print(f"   ❌ Error cancelling {order['pair']}: {exc}")
            fail_count += 1
        time.sleep(RATE_LIMIT_CANCEL_SECONDS)

    print(f"\n📊 Step 2 Summary: {success_count} cancelled, {fail_count} failed")
    return (success_count, fail_count)


# ---------------------------------------------------------------------------
# Step 3: Report dust (leave it alone)
# ---------------------------------------------------------------------------

def step3_report_dust(adapter: KrakenBrokerAdapter) -> None:
    """
    Identify and report dust positions (< $1.00). Takes NO action on them.
    """
    print_banner("STEP 3: Dust Report (< $1.00 → Ignored Forever)")

    balances = get_crypto_balances(adapter)
    dust = [b for b in balances if b['usd_value'] < DUST_THRESHOLD_USD]
    clean = [b for b in balances if b['usd_value'] >= DUST_THRESHOLD_USD]

    if clean:
        print(f"⚠️  {len(clean)} position(s) still ≥ $1.00 after Step 1 (review needed):")
        for bal in clean:
            print(f"   • {bal['currency']}: {bal['balance']:.8f} = ${bal['usd_value']:.2f}")
    else:
        print("✅ No significant crypto positions remain")

    if dust:
        print(f"\n⏭️  {len(dust)} dust position(s) < $1.00 — permanently ignored:")
        for bal in dust:
            print(f"   • {bal['currency']}: {bal['balance']:.8f} ≈ ${bal['usd_value']:.4f}")
    else:
        print("✅ No dust positions")


# ---------------------------------------------------------------------------
# Ideal-state check
# ---------------------------------------------------------------------------

def check_ideal_state(adapter: KrakenBrokerAdapter, account_name: str) -> Dict:
    """
    Evaluate the account against the ideal state targets and print a report.

    Ideal state:
        • 0–3 open positions
        • $50–$200 clean USD
        • No dust clutter

    Returns a dict with keys: positions_ok, usd_ok, dust_ok, all_ok,
    plus true_balance fields for the final summary.
    """
    print_banner(f"IDEAL STATE CHECK — {account_name}")

    tb = get_true_balance(adapter)
    show_true_balance(tb, label="AFTER CLEANUP")

    balances = tb['holdings']
    usd_balance = tb['usd_cash']
    open_orders = tb['open_orders']

    # Significant positions (≥ $1)
    sig_positions = [b for b in balances if b['usd_value'] >= DUST_THRESHOLD_USD]
    dust_positions = [b for b in balances if b['usd_value'] < DUST_THRESHOLD_USD]

    position_count = len(sig_positions)
    positions_ok = position_count <= IDEAL_MAX_POSITIONS
    usd_ok = IDEAL_MIN_USD <= usd_balance <= IDEAL_MAX_USD
    dust_ok = len(dust_positions) == 0

    pos_icon = "✅" if positions_ok else "⚠️ "
    usd_icon = "✅" if usd_ok else "⚠️ "
    dust_icon = "✅" if dust_ok else "⚠️ "

    print(f"{pos_icon} Positions   : {position_count} "
          f"(target: 0–{IDEAL_MAX_POSITIONS})")
    if sig_positions:
        for bal in sig_positions:
            print(f"      • {bal['currency']}: ${bal['usd_value']:.2f}")

    print(f"{usd_icon} USD balance : ${usd_balance:.2f} "
          f"(target: ${IDEAL_MIN_USD:.0f}–${IDEAL_MAX_USD:.0f})")

    print(f"{dust_icon} Dust clutter: {len(dust_positions)} item(s) "
          f"(target: 0)")
    if dust_positions:
        for bal in dust_positions:
            print(f"      • {bal['currency']}: ${bal['usd_value']:.4f} (< $1 — ignored)")

    if open_orders:
        print(f"⚠️  Open orders: {len(open_orders)} still pending")

    all_ok = positions_ok and usd_ok and dust_ok
    verdict = "✅ IDEAL STATE REACHED" if all_ok else "⚠️  NOT YET IDEAL"
    print(f"\n{'=' * 40}")
    print(f"  {verdict}")
    print(f"{'=' * 40}")

    return {
        'account': account_name,
        'positions': position_count,
        'usd_balance': usd_balance,
        'true_total': tb['true_total'],
        'dust_count': len(dust_positions),
        'positions_ok': positions_ok,
        'usd_ok': usd_ok,
        'dust_ok': dust_ok,
        'all_ok': all_ok,
    }


# ---------------------------------------------------------------------------
# Per-account cleanup orchestrator
# ---------------------------------------------------------------------------

def cleanup_account(
    account: Dict,
    dry_run: bool = False,
) -> Optional[Dict]:
    """
    Run the three-step cleanup for a single account and return the ideal-state
    result dict, or None if the account is not configured / unreachable.
    """
    name = account['name']
    api_key = os.getenv(account['key_env'])
    api_secret = os.getenv(account['secret_env'])

    print_account_header(name)

    if not api_key or not api_secret:
        print(f"⏭️  Skipping {name}: credentials not set")
        print(f"   (need {account['key_env']} and {account['secret_env']})")
        return None

    print(f"🔗 Connecting to Kraken ({name})...")
    adapter = KrakenBrokerAdapter(api_key=api_key, api_secret=api_secret)

    if not adapter.connect():
        print(f"❌ Could not connect to Kraken for {name} — skipping")
        return None

    print(f"✅ Connected ({name})\n")

    # ── TRUE BALANCE — before any changes ────────────────────────────────────
    tb_before = get_true_balance(adapter)
    show_true_balance(tb_before, label="BEFORE CLEANUP")

    # ── STEP 1: Sell ≥ $1 → USD ──────────────────────────────────────────────
    sell_ok, sell_fail = step1_sell_positions(adapter, dry_run=dry_run)

    # ── STEP 2: Cancel open orders ────────────────────────────────────────────
    cancel_ok, cancel_fail = step2_cancel_orders(adapter, dry_run=dry_run)

    # ── STEP 3: Report dust (no action) ──────────────────────────────────────
    step3_report_dust(adapter)

    if dry_run:
        print(f"\n🔍 DRY RUN complete for {name} — no trades executed")
        return None

    # Wait for orders to settle before final check
    if sell_ok > 0 or cancel_ok > 0:
        print(f"\n⏳ Waiting {SETTLE_WAIT_SECONDS}s for orders to settle…")
        time.sleep(SETTLE_WAIT_SECONDS)

    # ── Ideal-state check ─────────────────────────────────────────────────────
    return check_ideal_state(adapter, name)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            'Per-account Kraken cleanup: sell ≥$1 → cancel orders → ignore dust. '
            'Runs for Tania, Daivon, and Platform accounts.'
        )
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview actions without executing any trades',
    )
    parser.add_argument(
        '--account',
        choices=['tania', 'daivon', 'platform'],
        default=None,
        help='Only process one account (default: all three)',
    )
    args = parser.parse_args()

    print_banner("NIJA — PER-ACCOUNT KRAKEN CLEANUP")
    if args.dry_run:
        print("🔍 DRY RUN MODE — no actual trades will be executed\n")

    print("Target accounts: Tania · Daivon · Platform")
    print("Ideal state per account: 0–3 positions · $50–$200 USD · no dust")

    # Filter accounts if --account was specified
    accounts_to_run = (
        [a for a in ACCOUNTS if a['id'] == args.account]
        if args.account
        else ACCOUNTS
    )

    results: List[Dict] = []

    for account in accounts_to_run:
        result = cleanup_account(account, dry_run=args.dry_run)
        if result:
            results.append(result)

    # ── Final summary ─────────────────────────────────────────────────────────
    if results:
        print_banner("FINAL SUMMARY")
        all_ideal = True
        for r in results:
            status = "✅ IDEAL" if r['all_ok'] else "⚠️  NEEDS ATTENTION"
            print(f"  {r['account']:10s} │ "
                  f"true total ${r['true_total']:>8.2f} │ "
                  f"USD ${r['usd_balance']:>8.2f} │ "
                  f"{r['positions']} pos │ "
                  f"{r['dust_count']} dust │ "
                  f"{status}")
            if not r['all_ok']:
                all_ideal = False

        print()
        if all_ideal:
            print("✅ All accounts are in ideal state.")
        else:
            print("⚠️  One or more accounts have not reached ideal state.")
            print("   • If USD < $50:  deposit or allow the bot to compound profits")
            print("   • If USD > $200: review profit-taking / withdrawal settings")
            print("   • If positions > 3: re-run cleanup or adjust bot position cap")

    if args.dry_run:
        print("\nTo execute the cleanup, re-run without --dry-run:")
        print("  python scripts/clean_kraken_all_accounts.py")

    sys.exit(0)


if __name__ == '__main__':
    main()
