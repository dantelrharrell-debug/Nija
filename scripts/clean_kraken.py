#!/usr/bin/env python3
"""
Clean Kraken Account - Step 1: Cancel all orders and force-sell all positions

This script performs a complete cleanup of a Kraken account:
1. Cancel all open orders
2. Force-sell all crypto positions
3. Sweep dust (convert small residual balances to USD via ConvertFunds)
4. Verify that held in open orders = $0.00

Usage:
    python scripts/clean_kraken.py [--dry-run]

Options:
    --dry-run    Show what would be done without executing trades

Requirements:
    - KRAKEN_API_KEY and KRAKEN_API_SECRET environment variables must be set
    - API key must have permissions: Query Funds, Query/Create/Cancel Orders

Author: NIJA Trading Bot
Date: 2026-01-23
"""

import os
import sys
import argparse
import time
from typing import Dict, List, Tuple
from datetime import datetime

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bot'))

# Import required modules
from broker_integration import KrakenBrokerAdapter

# Import Kraken symbol mapper for proper symbol conversion
try:
    from kraken_symbol_mapper import convert_to_kraken
except ImportError:
    convert_to_kraken = None

# Import Kraken adapter utilities for symbol normalization
try:
    from kraken_adapter import normalize_kraken_symbol
except ImportError:
    normalize_kraken_symbol = None

# Constants
DUST_THRESHOLD_USD = 1.00  # Ignore positions below $1.00 USD value
KRAKEN_MIN_ORDER_COST = 10.00  # Kraken minimum order cost


def print_banner(message: str):
    """Print a formatted banner message."""
    print("\n" + "=" * 80)
    print(f"  {message}")
    print("=" * 80 + "\n")


def get_all_open_orders(adapter: KrakenBrokerAdapter) -> List[Dict]:
    """
    Get all open orders from Kraken.

    Returns:
        List of open order dictionaries with order_id, pair, type, volume, etc.
    """
    try:
        result = adapter._kraken_api_call('OpenOrders')

        if result and 'result' in result:
            open_orders = result['result'].get('open', {})
            orders = []

            for order_id, order in open_orders.items():
                descr = order.get('descr', {})
                orders.append({
                    'order_id': order_id,
                    'pair': descr.get('pair', 'UNKNOWN'),
                    'type': descr.get('type', 'UNKNOWN'),
                    'ordertype': descr.get('ordertype', 'UNKNOWN'),
                    'volume': float(order.get('vol', 0)),
                    'vol_exec': float(order.get('vol_exec', 0)),
                    'status': order.get('status', 'unknown')
                })

            return orders

        return []
    except Exception as e:
        print(f"❌ Error fetching open orders: {e}")
        return []


def cancel_all_orders(adapter: KrakenBrokerAdapter, dry_run: bool = False) -> Tuple[int, int]:
    """
    Cancel all open orders on Kraken.

    Args:
        adapter: KrakenBrokerAdapter instance
        dry_run: If True, only show what would be cancelled

    Returns:
        Tuple of (success_count, fail_count)
    """
    print_banner("STEP 1: Cancel All Open Orders")

    orders = get_all_open_orders(adapter)

    if not orders:
        print("✅ No open orders found - nothing to cancel")
        return (0, 0)

    print(f"📋 Found {len(orders)} open order(s):")
    for order in orders:
        print(f"   • {order['pair']}: {order['type']} {order['volume']:.8f} ({order['ordertype']}) - ID: {order['order_id'][:12]}...")

    if dry_run:
        print("\n🔍 DRY RUN: Would cancel all orders listed above")
        return (len(orders), 0)

    print("\n🔴 Cancelling all orders...")
    success_count = 0
    fail_count = 0

    for order in orders:
        order_id = order['order_id']
        try:
            success = adapter.cancel_order(order_id)
            if success:
                print(f"   ✅ Cancelled: {order['pair']} (ID: {order_id[:12]}...)")
                success_count += 1
            else:
                print(f"   ❌ Failed to cancel: {order['pair']} (ID: {order_id[:12]}...)")
                fail_count += 1

            # Rate limiting: small delay between cancellations
            # Kraken private API rate limit: ~15 requests per second
            time.sleep(0.1)

        except Exception as e:
            print(f"   ❌ Error cancelling {order['pair']}: {e}")
            fail_count += 1

    print(f"\n📊 Cancellation Summary: {success_count} succeeded, {fail_count} failed")
    return (success_count, fail_count)


def convert_asset_code(asset: str) -> str:
    """
    Convert Kraken asset code to standard currency symbol.

    Args:
        asset: Kraken asset code (e.g., 'XXBT', 'XETH', 'ADA')

    Returns:
        Standard currency symbol (e.g., 'BTC', 'ETH', 'ADA')
    """
    # Handle X-prefixed assets (common for major cryptocurrencies)
    if asset.startswith('X') and len(asset) == 4:
        # Remove X prefix: XXBT -> XBT, XETH -> ETH
        asset = asset[1:]

    # Special case: XBT is Bitcoin
    if asset == 'XBT':
        return 'BTC'

    # Special case: XDG is Dogecoin
    if asset == 'XDG':
        return 'DOGE'

    # Special case: XLM is Stellar (not XMLM)
    if asset == 'XLM':
        return 'XLM'

    # For most other assets, return as-is
    return asset


def get_ticker_pair_for_asset(asset: str, currency: str) -> str:
    """
    Construct the correct Kraken ticker pair for an asset.

    This handles the various Kraken pair naming conventions:
    - Major assets: XXBTZUSD, XETHZUSD
    - Some altcoins: ADAUSD, DOTUSD (no X prefix)
    - Others: varies by asset

    Args:
        asset: Original Kraken asset code
        currency: Converted currency symbol

    Returns:
        Kraken ticker pair string
    """
    # Try different ticker pair formats
    # Format 1: Original asset + USD (works for many altcoins)
    candidates = [
        f'{asset}USD',      # ADAUSD, DOTUSD
        f'{asset}ZUSD',     # Some assets use ZUSD
        f'X{currency}ZUSD', # X-prefixed format
        f'{currency}USD',   # Simple format
    ]

    # Return the first candidate (caller will try all via API)
    return candidates[0]


def get_all_crypto_balances(adapter: KrakenBrokerAdapter) -> List[Dict]:
    """
    Get all non-zero crypto balances from Kraken (excluding USD/USDT).

    Returns:
        List of balance dictionaries with asset, balance, usd_value, etc.
    """
    try:
        balance_result = adapter._kraken_api_call('Balance')

        if not balance_result or 'result' not in balance_result:
            return []

        balances = []
        result = balance_result['result']

        for asset, amount in result.items():
            balance_val = float(amount)

            # Skip USD/USDT and zero balances
            if asset in ['ZUSD', 'USDT', 'USD'] or balance_val <= 0:
                continue

            # Convert Kraken asset code to standard currency symbol
            currency = convert_asset_code(asset)

            # Get current price using multiple ticker pair attempts
            current_price = 0.0
            ticker_pair_used = None

            try:
                # Try multiple ticker pair formats
                ticker_candidates = [
                    f'{asset}USD',      # Direct format: ADAUSD
                    f'{asset}ZUSD',     # Z-suffix format
                    f'X{currency}ZUSD', # X-prefix format: XETHZUSD
                    f'{currency}USD',   # Simple format: BTCUSD
                ]

                # Add special cases for major coins
                if currency == 'BTC':
                    ticker_candidates.insert(0, 'XXBTZUSD')
                    ticker_candidates.insert(1, 'XBTUSD')
                elif currency == 'ETH':
                    ticker_candidates.insert(0, 'XETHZUSD')
                    ticker_candidates.insert(1, 'ETHUSD')

                # Try each ticker pair format until one works
                for ticker_pair in ticker_candidates:
                    try:
                        ticker_result = adapter._kraken_api_call('Ticker', {'pair': ticker_pair})

                        if ticker_result and 'result' in ticker_result:
                            # Kraken may return with a different key than requested
                            ticker_data = None

                            # Try exact match first
                            if ticker_pair in ticker_result['result']:
                                ticker_data = ticker_result['result'][ticker_pair]
                            # Try any available ticker (first result)
                            elif ticker_result['result']:
                                ticker_data = list(ticker_result['result'].values())[0]

                            if ticker_data:
                                last_price = ticker_data.get('c', [0, 0])
                                current_price = float(last_price[0]) if isinstance(last_price, list) else float(last_price)

                                if current_price > 0:
                                    ticker_pair_used = ticker_pair
                                    break  # Success, stop trying
                    except Exception:
                        continue  # Try next ticker pair format

                usd_value = balance_val * current_price if current_price > 0 else 0

                balances.append({
                    'asset': asset,
                    'currency': currency,
                    'balance': balance_val,
                    'current_price': current_price,
                    'usd_value': usd_value,
                    'ticker_pair': ticker_pair_used
                })

            except Exception as price_err:
                print(f"   ⚠️  Could not get price for {currency} (asset: {asset}): {price_err}")
                # Add with unknown price - will be excluded from selling
                balances.append({
                    'asset': asset,
                    'currency': currency,
                    'balance': balance_val,
                    'current_price': 0.0,
                    'usd_value': 0.0,
                    'ticker_pair': None
                })

        return balances

    except Exception as e:
        print(f"❌ Error fetching balances: {e}")
        return []


def force_sell_all_positions(adapter: KrakenBrokerAdapter, dry_run: bool = False) -> Tuple[int, int, int]:
    """
    Force-sell all crypto positions using market orders.

    Positions above Kraken's $10 minimum are sold immediately via market order.
    Positions below that threshold are left for the dust sweep step.

    Args:
        adapter: KrakenBrokerAdapter instance
        dry_run: If True, only show what would be sold

    Returns:
        Tuple of (success_count, fail_count, skipped_count)
    """
    print_banner("STEP 2: Force-Sell All Positions")

    balances = get_all_crypto_balances(adapter)

    if not balances:
        print("✅ No crypto balances found - nothing to sell")
        return (0, 0, 0)

    # Separate positions into sellable (above Kraken minimum) and small (below minimum, handled by dust sweep)
    sellable = []
    too_small = []

    for bal in balances:
        if bal['usd_value'] >= KRAKEN_MIN_ORDER_COST:
            sellable.append(bal)
        else:
            too_small.append(bal)

    # Show positions
    if sellable:
        print(f"📋 Found {len(sellable)} position(s) to sell:")
        for bal in sellable:
            print(f"   • {bal['currency']}: {bal['balance']:.8f} @ ${bal['current_price']:.2f} = ${bal['usd_value']:.2f}")

    if too_small:
        print(f"\n⏭️  Found {len(too_small)} small position(s) (below ${KRAKEN_MIN_ORDER_COST:.2f}) - will be handled by dust sweep:")
        for bal in too_small:
            print(f"   • {bal['currency']}: {bal['balance']:.8f} = ${bal['usd_value']:.4f}")

    if not sellable:
        print(f"\n✅ No positions above ${KRAKEN_MIN_ORDER_COST:.2f} to sell via market order")
        return (0, 0, len(too_small))

    if dry_run:
        print(f"\n🔍 DRY RUN: Would sell {len(sellable)} position(s) listed above")
        return (len(sellable), 0, len(too_small))

    print("\n🔴 Force-selling all positions...")
    success_count = 0
    fail_count = 0

    for bal in sellable:
        currency = bal['currency']
        balance = bal['balance']
        usd_value = bal['usd_value']

        try:
            # Construct symbol in standard format (e.g., BTC-USD)
            # The broker adapter will convert it to Kraken format
            symbol = f"{currency}-USD"

            print(f"   🔴 Selling {currency}: {balance:.8f} (${usd_value:.2f})...")

            # Place market sell order
            # Note: adapter._convert_to_kraken_symbol will handle format conversion
            result = adapter.place_market_order(
                symbol=symbol,
                side='sell',
                size=balance,
                size_type='base'
            )

            if result and result.get('status') not in ['error', 'skipped']:
                order_id = result.get('order_id', 'N/A')
                print(f"      ✅ SOLD: {currency} (Order ID: {str(order_id)[:12]}...)")
                success_count += 1
            else:
                error = result.get('error', 'Unknown error') if result else 'No response'
                print(f"      ❌ FAILED: {currency} - {error}")
                fail_count += 1

            # Rate limiting: delay between orders to avoid hitting API limits
            # Kraken private API rate limit: ~15 requests per second
            # Use 0.2s delay to be safe (5 requests/second)
            time.sleep(0.2)

        except Exception as e:
            print(f"   ❌ Error selling {currency}: {e}")
            fail_count += 1

    print(f"\n📊 Sell Summary: {success_count} succeeded, {fail_count} failed, {len(too_small)} deferred to dust sweep")
    return (success_count, fail_count, len(too_small))


def sweep_dust_positions(adapter: KrakenBrokerAdapter, dry_run: bool = False) -> Tuple[int, int]:
    """
    Sweep all remaining dust and small positions by converting them to USD.

    Uses Kraken's ConvertFunds endpoint which can handle amounts below the
    regular $10 minimum order cost.  Falls back to a standard market order
    for any assets that ConvertFunds does not support.

    Args:
        adapter: KrakenBrokerAdapter instance
        dry_run: If True, only show what would be converted

    Returns:
        Tuple of (success_count, fail_count)
    """
    print_banner("STEP 3: Sweep Dust Positions")

    balances = get_all_crypto_balances(adapter)

    if not balances:
        print("✅ No crypto balances remaining - nothing to sweep")
        return (0, 0)

    print(f"🧹 Found {len(balances)} residual position(s) to sweep:")
    for bal in balances:
        label = "DUST" if bal['usd_value'] < DUST_THRESHOLD_USD else "SMALL"
        print(f"   • [{label}] {bal['currency']}: {bal['balance']:.8f} = ${bal['usd_value']:.4f}")

    if dry_run:
        print(f"\n🔍 DRY RUN: Would convert {len(balances)} position(s) to USD")
        return (len(balances), 0)

    print("\n🧹 Converting residual positions to USD...")
    success_count = 0
    fail_count = 0

    for bal in balances:
        currency = bal['currency']
        asset = bal.get('asset', currency)   # Kraken-internal asset code (e.g., 'XXBT', 'ADA')
        balance = bal['balance']
        usd_value = bal['usd_value']

        if not asset:
            print(f"   ⚠️  Skipping {currency}: no Kraken asset code found")
            fail_count += 1
            continue

        print(f"   🧹 Sweeping {currency}: {balance:.8f} (≈${usd_value:.4f})...")

        converted = False

        # ── Method 1: Kraken ConvertFunds (handles sub-minimum amounts) ──────
        try:
            result = adapter._kraken_api_call('ConvertFunds', {
                'from_asset': asset,
                'to_asset': 'ZUSD',
                'from_amount': str(balance),
            })

            errors = result.get('error', []) if result else ['No response']
            if result and not errors and 'result' in result:
                order_id = result['result'].get('order_id', 'N/A')
                print(f"      ✅ CONVERTED via ConvertFunds: {currency} → USD"
                      f" (ref: {str(order_id)[:12]}...)")
                success_count += 1
                converted = True
            else:
                error_str = ', '.join(errors) if isinstance(errors, list) else str(errors)
                print(f"      ⚠️  ConvertFunds declined ({error_str}) – trying market order…")

        except Exception as exc:
            print(f"      ⚠️  ConvertFunds raised an error ({exc}) – trying market order…")

        # ── Method 2: Standard market sell (fallback) ─────────────────────────
        if not converted:
            try:
                symbol = f"{currency}-USD"
                sell_result = adapter.place_market_order(
                    symbol=symbol,
                    side='sell',
                    size=balance,
                    size_type='base',
                )

                if sell_result and sell_result.get('status') not in ['error', 'skipped']:
                    order_id = sell_result.get('order_id', 'N/A')
                    print(f"      ✅ SOLD via market order: {currency}"
                          f" (Order ID: {str(order_id)[:12]}...)")
                    success_count += 1
                    converted = True
                else:
                    error = (sell_result.get('error', 'Unknown error')
                             if sell_result else 'No response')
                    print(f"      ❌ FAILED: {currency} – {error}")
                    fail_count += 1

            except Exception as exc:
                print(f"      ❌ Error sweeping {currency}: {exc}")
                fail_count += 1

        # Small delay between API calls to respect rate limits
        time.sleep(0.2)

    print(f"\n📊 Dust Sweep Summary: {success_count} swept, {fail_count} failed")
    return (success_count, fail_count)


def verify_cleanup(adapter: KrakenBrokerAdapter) -> bool:
    """
    Verify that the account is clean: no open orders and no significant positions.

    Returns:
        True if account is clean, False otherwise
    """
    print_banner("STEP 4: Verify Cleanup")

    # Check open orders
    orders = get_all_open_orders(adapter)
    if orders:
        print(f"⚠️  WARNING: {len(orders)} open order(s) still remain")
        return False
    else:
        print("✅ Open orders: 0")

    # Check balances
    balances = get_all_crypto_balances(adapter)

    if not balances:
        print("✅ Crypto balances: 0")
        print("\n" + "=" * 80)
        print("  ✅ CLEANUP SUCCESSFUL - Held in open orders: $0.00")
        print("=" * 80 + "\n")
        return True

    # Check if any significant positions remain
    significant = [b for b in balances if b['usd_value'] >= DUST_THRESHOLD_USD]

    if significant:
        print(f"⚠️  WARNING: {len(significant)} significant position(s) still remain:")
        for bal in significant:
            print(f"   • {bal['currency']}: {bal['balance']:.8f} = ${bal['usd_value']:.2f}")
        return False
    else:
        # Only dust remains
        print(f"✅ Only {len(balances)} dust position(s) remain (all < ${DUST_THRESHOLD_USD}):")
        for bal in balances:
            print(f"   • {bal['currency']}: {bal['balance']:.8f} = ${bal['usd_value']:.4f}")

        print("\n" + "=" * 80)
        print("  ✅ CLEANUP SUCCESSFUL - Held in open orders: $0.00")
        print("  (Dust positions below $1.00 are ignored)")
        print("=" * 80 + "\n")
        return True


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description='Clean Kraken account: cancel all orders and force-sell all positions'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without executing trades'
    )
    args = parser.parse_args()

    print_banner("KRAKEN ACCOUNT CLEANUP - Step 1")

    if args.dry_run:
        print("🔍 DRY RUN MODE: No actual trades will be executed\n")

    # Check for API credentials
    api_key = os.getenv('KRAKEN_API_KEY') or os.getenv('KRAKEN_PLATFORM_API_KEY')
    api_secret = os.getenv('KRAKEN_API_SECRET') or os.getenv('KRAKEN_PLATFORM_API_SECRET')

    if not api_key or not api_secret:
        print("❌ ERROR: Kraken API credentials not found")
        print("\nPlease set environment variables:")
        print("  - KRAKEN_API_KEY or KRAKEN_PLATFORM_API_KEY")
        print("  - KRAKEN_API_SECRET or KRAKEN_PLATFORM_API_SECRET")
        sys.exit(1)

    # Initialize Kraken adapter
    print("🔗 Connecting to Kraken...")
    adapter = KrakenBrokerAdapter(api_key=api_key, api_secret=api_secret)

    if not adapter.connect():
        print("❌ Failed to connect to Kraken API")
        print("\nPlease verify:")
        print("  1. API credentials are correct")
        print("  2. API key has required permissions:")
        print("     - Query Funds")
        print("     - Query Open Orders & Trades")
        print("     - Create & Modify Orders")
        print("     - Cancel/Close Orders")
        sys.exit(1)

    print("✅ Connected to Kraken\n")

    # Get initial account balance
    try:
        balance_info = adapter.get_account_balance()
        if not balance_info.get('error'):
            total = balance_info.get('total_balance', 0)
            print(f"💰 Current USD/USDT Balance: ${total:.2f}\n")
    except Exception as e:
        print(f"⚠️  Could not fetch USD balance: {e}\n")

    # Execute cleanup steps
    try:
        # Step 1: Cancel all open orders
        cancel_success, cancel_fail = cancel_all_orders(adapter, dry_run=args.dry_run)

        # Step 2: Force-sell all positions above Kraken's minimum order cost
        sell_success, sell_fail, small_count = force_sell_all_positions(adapter, dry_run=args.dry_run)

        # Step 3: Sweep remaining dust and sub-minimum positions
        sweep_success, sweep_fail = sweep_dust_positions(adapter, dry_run=args.dry_run)

        if args.dry_run:
            print_banner("DRY RUN COMPLETE")
            print("No actual trades were executed.")
            print("\nTo execute the cleanup, run without --dry-run flag:")
            print("  python scripts/clean_kraken.py")
            return

        # Small delay for orders to settle
        if sell_success > 0 or sweep_success > 0:
            print("\n⏳ Waiting 5 seconds for orders to settle...")
            time.sleep(5)

        # Step 4: Verify cleanup
        success = verify_cleanup(adapter)

        # Show final balance
        try:
            balance_info = adapter.get_account_balance()
            if not balance_info.get('error'):
                total = balance_info.get('total_balance', 0)
                print(f"💰 Final USD/USDT Balance: ${total:.2f}")
        except Exception as e:
            print(f"⚠️  Could not fetch final balance: {e}")

        if success:
            print("\n✅ Account is ready for restart with clean state")
            sys.exit(0)
        else:
            print("\n⚠️  Some positions or orders remain - manual review recommended")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
