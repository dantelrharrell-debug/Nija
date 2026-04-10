#!/usr/bin/env python3
"""
NIJA Emergency Reset Module
============================

Performs a complete, ordered emergency shutdown and cleanup:

1. Stop the bot       — activate the global kill switch
2. Cancel open orders — cancel every pending order on every connected broker
3. Liquidate          — force-sell all open positions (market orders, no checks)
4. Sweep dust         — close any remaining sub-threshold positions
5. Delete state files — remove positions.json and open_positions.json

This module is intentionally self-contained so it can be called from a CLI
script or imported by other safety systems.

Author: NIJA Trading Systems
Date: March 2026
"""

import logging
import os
import signal as _signal
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

logger = logging.getLogger("nija.emergency_reset")

# Module-level kill switch import — enables mocking in tests
try:
    from bot.kill_switch import get_kill_switch
except ImportError:
    try:
        from kill_switch import get_kill_switch
    except ImportError:
        get_kill_switch = None  # type: ignore[assignment]

# ────────────────────────────────────────────────────────────────────────────
# Position-file candidates (checked in order; all present files are removed)
# ────────────────────────────────────────────────────────────────────────────
_POSITION_FILE_CANDIDATES = [
    "positions.json",
    "data/positions.json",
    "data/open_positions.json",
    "bot/data/positions.json",
    "bot/data/open_positions.json",
]


# ============================================================================
# STEP 1: Stop the bot (kill switch)
# ============================================================================

def stop_bot(reason: str = "Emergency reset") -> bool:
    """
    Activate the global NIJA kill switch to halt all new trading.

    Args:
        reason: Human-readable reason logged alongside the activation.

    Returns:
        True if kill switch was activated (or was already active).
    """
    try:
        if get_kill_switch is None:
            logger.error("❌ Kill switch module not available")
            return False

        kill_switch = get_kill_switch()
        if not kill_switch.is_active():
            kill_switch.activate(reason, source="EmergencyReset")
            logger.warning(f"🛑 Kill switch ACTIVATED: {reason}")
        else:
            logger.info("🛑 Kill switch already active")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to activate kill switch: {e}")
        return False


# ============================================================================
# STEP 2: Cancel all open orders
# ============================================================================

def _cancel_orders_coinbase(broker) -> int:
    """
    Cancel all open orders on a Coinbase broker instance.

    Returns number of orders cancelled.
    """
    cancelled = 0
    try:
        client = getattr(broker, 'client', None)
        if client is None:
            logger.warning("   Coinbase client not available for order cancellation")
            return 0

        # Try the Advanced Trade list_orders endpoint
        try:
            resp = client.list_orders(order_status=["OPEN"])
            orders = getattr(resp, 'orders', None)
            if isinstance(resp, dict):
                orders = resp.get('orders', [])
            if orders is None:
                orders = []
        except Exception:
            orders = []

        for order in orders:
            order_id = (order.get('order_id') if isinstance(order, dict)
                        else getattr(order, 'order_id', None))
            if not order_id:
                continue
            try:
                client.cancel_orders(order_ids=[order_id])
                logger.info(f"   ✅ Cancelled Coinbase order: {order_id}")
                cancelled += 1
            except Exception as exc:
                logger.warning(f"   ⚠️  Could not cancel order {order_id}: {exc}")

    except Exception as e:
        logger.error(f"   ❌ Coinbase order cancellation error: {e}")

    return cancelled


def _cancel_orders_kraken(broker) -> int:
    """
    Cancel all open orders on a Kraken broker instance.

    Returns number of orders cancelled.
    """
    cancelled = 0
    try:
        api_call = getattr(broker, '_kraken_api_call', None)
        if api_call is None:
            logger.warning("   Kraken API call helper not available")
            return 0

        result = api_call('OpenOrders')
        if not result or 'result' not in result:
            return 0

        open_orders = result['result'].get('open', {})
        for order_id in list(open_orders.keys()):
            try:
                cancel_result = api_call('CancelOrder', {'txid': order_id})
                if cancel_result and 'result' in cancel_result:
                    count = cancel_result['result'].get('count', 0)
                    if count > 0:
                        logger.info(f"   ✅ Cancelled Kraken order: {order_id}")
                        cancelled += 1
                        continue
                logger.warning(f"   ⚠️  Kraken cancel returned unexpected result for {order_id}")
            except Exception as exc:
                logger.warning(f"   ⚠️  Could not cancel Kraken order {order_id}: {exc}")

    except Exception as e:
        logger.error(f"   ❌ Kraken order cancellation error: {e}")

    return cancelled


def cancel_all_open_orders(brokers: List) -> Dict[str, int]:
    """
    Cancel every open order across all provided broker instances.

    Args:
        brokers: List of broker instances (CoinbaseBroker, KrakenBroker, etc.)

    Returns:
        Dict mapping broker name → number of orders cancelled.
    """
    results: Dict[str, int] = {}
    for broker in brokers:
        broker_name = getattr(broker, 'broker_type', type(broker).__name__)
        broker_name = str(broker_name)
        logger.info(f"🗑️  Cancelling orders on {broker_name}…")

        # Detect broker type and delegate to the right helper
        type_name = type(broker).__name__.lower()
        if 'coinbase' in type_name:
            count = _cancel_orders_coinbase(broker)
        elif 'kraken' in type_name:
            count = _cancel_orders_kraken(broker)
        else:
            # Generic: try cancel_order on every known order_id via get_orders / order_status
            count = 0
            logger.warning(f"   ⚠️  No specialised order cancellation for {broker_name}; skipping")

        results[broker_name] = count
        logger.info(f"   Cancelled {count} order(s) on {broker_name}")

    return results


# ============================================================================
# STEP 3: Liquidate all positions
# ============================================================================

def liquidate_all_positions(brokers: List) -> Dict[str, int]:
    """
    Force-sell every open position across all provided broker instances.

    Uses force_liquidate() where available; falls back to close_position().

    Args:
        brokers: List of broker instances.

    Returns:
        Dict mapping broker name → number of positions liquidated.
    """
    results: Dict[str, int] = {}
    for broker in brokers:
        broker_name = str(getattr(broker, 'broker_type', type(broker).__name__))
        logger.info(f"💥 Liquidating positions on {broker_name}…")
        count = 0

        try:
            positions = broker.get_positions()
            if not positions:
                logger.info(f"   No positions to liquidate on {broker_name}")
                results[broker_name] = 0
                continue

            for pos in positions:
                symbol = pos.get('symbol', 'UNKNOWN')
                quantity = float(pos.get('quantity', pos.get('size', 0)))

                if quantity <= 0:
                    continue

                try:
                    force_liq = getattr(broker, 'force_liquidate', None)
                    if force_liq:
                        result = force_liq(
                            symbol=symbol,
                            quantity=quantity,
                            reason="Emergency reset liquidation"
                        )
                    else:
                        result = broker.place_market_order(
                            symbol=symbol,
                            side='sell',
                            quantity=quantity,
                            size_type='base',
                            ignore_balance=True,
                            ignore_min_trade=True,
                            force_liquidate=True,
                        )

                    status = result.get('status', 'unknown') if result else 'unknown'
                    if status in ('filled', 'completed', 'success'):
                        logger.info(f"   ✅ Liquidated {symbol}: qty={quantity}")
                        count += 1
                    else:
                        logger.warning(f"   ⚠️  Liquidation order for {symbol} returned status={status}")

                except Exception as pos_err:
                    logger.error(f"   ❌ Failed to liquidate {symbol}: {pos_err}")

        except Exception as e:
            logger.error(f"   ❌ Error fetching positions from {broker_name}: {e}")

        results[broker_name] = count
        logger.info(f"   Liquidated {count} position(s) on {broker_name}")

    return results


# ============================================================================
# STEP 4: Sweep dust
# ============================================================================

def sweep_dust(brokers: List, dust_threshold_usd: float = 1.00) -> Dict[str, int]:
    """
    Close any remaining positions below dust_threshold_usd on every broker.

    This runs *after* liquidation to catch any positions that survived because
    they were too small for the regular liquidation order minimum.

    Args:
        brokers: List of broker instances.
        dust_threshold_usd: Positions with USD value below this are swept.

    Returns:
        Dict mapping broker name → number of dust positions swept.
    """
    results: Dict[str, int] = {}
    for broker in brokers:
        broker_name = str(getattr(broker, 'broker_type', type(broker).__name__))
        logger.info(f"🧹 Sweeping dust on {broker_name} (threshold=${dust_threshold_usd:.2f})…")
        count = 0

        try:
            # Prefer BrokerDustCleanup if available
            try:
                try:
                    from bot.broker_dust_cleanup import BrokerDustCleanup
                except ImportError:
                    from broker_dust_cleanup import BrokerDustCleanup

                cleanup = BrokerDustCleanup(
                    dust_threshold_usd=dust_threshold_usd,
                    dry_run=False,
                )
                summary = cleanup.cleanup_all_dust(broker)
                count = summary.get('closed', 0)

            except ImportError:
                # Fallback: manual dust sweep
                positions = broker.get_positions()
                for pos in (positions or []):
                    symbol = pos.get('symbol', 'UNKNOWN')
                    quantity = float(pos.get('quantity', pos.get('size', 0)))
                    usd_value = float(pos.get('usd_value', pos.get('value_usd', 0)))

                    if usd_value <= 0:
                        # Estimate from current_price if available
                        price = float(pos.get('current_price', 0))
                        usd_value = quantity * price

                    if 0 < usd_value < dust_threshold_usd:
                        try:
                            broker.place_market_order(
                                symbol=symbol,
                                side='sell',
                                quantity=quantity,
                                size_type='base',
                                force_liquidate=True,
                                ignore_min_trade=True,
                            )
                            logger.info(f"   🗑️  Swept dust: {symbol} (${usd_value:.4f})")
                            count += 1
                        except Exception as dust_err:
                            logger.warning(f"   ⚠️  Could not sweep {symbol}: {dust_err}")

        except Exception as e:
            logger.error(f"   ❌ Dust sweep error on {broker_name}: {e}")

        results[broker_name] = count
        logger.info(f"   Swept {count} dust position(s) on {broker_name}")

    return results


# ============================================================================
# STEP 5: Delete position tracking files
# ============================================================================

def reset_cached_balances(brokers: Optional[List] = None) -> int:
    """
    Clear all in-memory balance caches so the next fetch hits the exchange API.

    Resets:
        • broker._last_known_balance  on every provided broker instance
        • multi_account_manager._balance_cache  (via clear_balance_cache())

    Args:
        brokers: List of connected broker instances whose ``_last_known_balance``
                 attribute should be cleared.  Pass None to skip per-broker reset.

    Returns:
        Number of caches that were cleared.
    """
    cleared = 0

    # Per-broker last-known-balance cache
    for broker in (brokers or []):
        if hasattr(broker, '_last_known_balance'):
            broker._last_known_balance = None
            cleared += 1
            logger.warning(
                f"🔄 Cleared cached balance on {getattr(broker, 'broker_type', type(broker).__name__)}"
            )

    # Multi-account manager balance cache (import lazily to avoid circular deps)
    try:
        try:
            from bot.multi_account_broker_manager import get_multi_account_manager
        except ImportError:
            from multi_account_broker_manager import get_multi_account_manager as get_multi_account_manager
        manager = get_multi_account_manager()
        if manager and hasattr(manager, 'clear_balance_cache'):
            manager.clear_balance_cache()
            cleared += 1
            logger.warning("🔄 Cleared multi-account manager balance cache")
    except Exception as exc:
        logger.debug(f"Multi-account balance cache reset skipped: {exc}")

    if cleared:
        logger.warning(f"✅ Reset {cleared} balance cache(s)")
    else:
        logger.info("ℹ️  No balance caches found to reset")

    return cleared


def delete_position_files(extra_paths: Optional[List[str]] = None) -> List[str]:
    """
    Delete positions.json and related position-tracking files.

    Searches the standard candidate paths relative to the repository root
    (i.e., relative to the current working directory) and also removes any
    paths passed explicitly in extra_paths.

    Args:
        extra_paths: Additional file paths to delete.

    Returns:
        List of file paths that were successfully deleted.
    """
    deleted: List[str] = []
    candidates = list(_POSITION_FILE_CANDIDATES)
    if extra_paths:
        candidates.extend(extra_paths)

    for path in candidates:
        abs_path = os.path.abspath(path)
        if os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
                logger.warning(f"🗑️  Deleted position file: {abs_path}")
                deleted.append(abs_path)
            except Exception as e:
                logger.error(f"❌ Could not delete {abs_path}: {e}")

    if deleted:
        logger.warning(f"✅ Deleted {len(deleted)} position file(s): {deleted}")
    else:
        logger.info("ℹ️  No position files found to delete")

    return deleted


# ============================================================================
# ORCHESTRATOR
# ============================================================================

def run_emergency_reset(
    brokers: Optional[List] = None,
    dust_threshold_usd: float = 1.00,
    extra_position_files: Optional[List[str]] = None,
    stop_reason: str = "Emergency reset",
) -> Dict[str, Any]:
    """
    Execute the full emergency reset sequence:

        1. Stop the bot (kill switch)
        2. Cancel all open orders
        3. Liquidate all positions
        4. Sweep dust
        5. Delete position tracking files
        6. Reset cached balances

    Args:
        brokers: List of connected broker instances.  If None, only steps that
                 do not require a broker (1, 5 & 6) are executed.
        dust_threshold_usd: USD value threshold for dust positions (step 4).
        extra_position_files: Additional file paths to delete (step 5).
        stop_reason: Reason string recorded in the kill-switch log.

    Returns:
        Dict with keys:
            kill_switch_activated (bool)
            orders_cancelled      (dict: broker→count)
            positions_liquidated  (dict: broker→count)
            dust_swept            (dict: broker→count)
            files_deleted         (list of str)
            caches_cleared        (int)
            completed_at          (ISO-8601 str)
    """
    logger.warning("=" * 70)
    logger.warning("🚨 NIJA EMERGENCY RESET INITIATED")
    logger.warning("=" * 70)
    start = datetime.now(timezone.utc)

    summary: Dict[str, Any] = {
        'kill_switch_activated': False,
        'orders_cancelled': {},
        'positions_liquidated': {},
        'dust_swept': {},
        'files_deleted': [],
        'caches_cleared': 0,
        'completed_at': None,
    }

    # ── Step 1: Stop the bot ──────────────────────────────────────────────
    logger.warning("STEP 1/6: Stopping bot…")
    summary['kill_switch_activated'] = stop_bot(stop_reason)

    active_brokers = brokers or []

    # ── Step 2: Cancel open orders ────────────────────────────────────────
    logger.warning("STEP 2/6: Cancelling all open orders…")
    if active_brokers:
        summary['orders_cancelled'] = cancel_all_open_orders(active_brokers)
    else:
        logger.info("   No brokers provided; skipping order cancellation")

    # Brief pause to allow cancellations to propagate before liquidating
    if active_brokers:
        time.sleep(1.0)

    # ── Step 3: Liquidate all positions ───────────────────────────────────
    logger.warning("STEP 3/6: Liquidating all positions…")
    if active_brokers:
        summary['positions_liquidated'] = liquidate_all_positions(active_brokers)
    else:
        logger.info("   No brokers provided; skipping liquidation")

    if active_brokers:
        time.sleep(1.0)

    # ── Step 4: Sweep dust ────────────────────────────────────────────────
    logger.warning("STEP 4/6: Sweeping dust positions…")
    if active_brokers:
        summary['dust_swept'] = sweep_dust(active_brokers, dust_threshold_usd)
    else:
        logger.info("   No brokers provided; skipping dust sweep")

    # ── Step 5: Delete position files ─────────────────────────────────────
    logger.warning("STEP 5/6: Deleting position tracking files…")
    summary['files_deleted'] = delete_position_files(extra_position_files)

    # ── Step 6: Reset cached balances ─────────────────────────────────────
    logger.warning("STEP 6/6: Resetting cached balances…")
    summary['caches_cleared'] = reset_cached_balances(active_brokers if active_brokers else None)

    # ── Final summary ─────────────────────────────────────────────────────
    summary['completed_at'] = datetime.now(timezone.utc).isoformat()
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()

    logger.warning("=" * 70)
    logger.warning("🏁 EMERGENCY RESET COMPLETE")
    logger.warning("=" * 70)
    logger.warning(f"   Kill switch activated : {summary['kill_switch_activated']}")
    if active_brokers:
        total_cancelled = sum(summary['orders_cancelled'].values())
        total_liquidated = sum(summary['positions_liquidated'].values())
        total_swept = sum(summary['dust_swept'].values())
        logger.warning(f"   Orders cancelled     : {total_cancelled}")
        logger.warning(f"   Positions liquidated : {total_liquidated}")
        logger.warning(f"   Dust swept           : {total_swept}")
    logger.warning(f"   Files deleted        : {len(summary['files_deleted'])}")
    logger.warning(f"   Caches cleared       : {summary['caches_cleared']}")
    logger.warning(f"   Duration             : {elapsed:.1f}s")
    logger.warning("=" * 70)

    return summary


# ============================================================================
# STEP 7: Restart the bot process
# ============================================================================

def restart_process() -> None:
    """
    Restart the current Python process in-place.

    Uses ``os.execv`` to replace the running process with a fresh copy of the
    same Python interpreter and command-line arguments.  All in-memory state
    (kill switch, position cache, balance cache) is discarded because the new
    process starts from scratch.

    If ``os.execv`` is unavailable or raises, falls back to sending ``SIGTERM``
    to the current process so the deployment platform (Railway / Docker) restarts
    the container automatically.  If that also fails, calls ``sys.exit(0)``.
    """
    logger.warning("=" * 70)
    logger.warning("🔄 NIJA BOT RESTART INITIATED")
    logger.warning("   Replacing process: %s %s", sys.executable, " ".join(sys.argv))
    logger.warning("=" * 70)

    # Give log handlers a moment to flush before exec replaces the process.
    time.sleep(0.5)

    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
        # If execv succeeds the line below is never reached.
    except Exception as exec_err:
        logger.error("os.execv failed (%s) — sending SIGTERM so platform restarts", exec_err)
        try:
            os.kill(os.getpid(), _signal.SIGTERM)
        except Exception:
            logger.error("SIGTERM failed — calling sys.exit(0)")
            sys.exit(0)


# ============================================================================
# ORCHESTRATOR: clear-and-restart
# ============================================================================

def clear_and_restart(
    brokers: Optional[List] = None,
    dust_threshold_usd: float = 1.00,
    extra_position_files: Optional[List[str]] = None,
    verify_clear: bool = True,
    max_verify_attempts: int = 3,
    verify_wait_s: float = 5.0,
    stop_reason: str = "Clear-and-restart",
) -> None:
    """
    Close ALL positions, wipe state files, then restart the bot process.

    Sequence
    --------
    A. Run the full emergency reset (cancel orders → liquidate → sweep dust →
       delete state files → clear balance caches).
    B. Optionally poll the exchange to confirm every position is gone.
    C. Replace the current process via :func:`restart_process`.

    Args:
        brokers:               Connected broker instances.  When ``None`` only
                               state-file deletion and cache-clearing run
                               (liquidation steps are skipped).
        dust_threshold_usd:    USD value floor for the dust-sweep step.
        extra_position_files:  Additional state-file paths to delete.
        verify_clear:          When ``True``, poll the broker after liquidation
                               to confirm all positions are gone before restarting.
        max_verify_attempts:   Number of polling attempts before giving up.
        verify_wait_s:         Seconds to wait between verification attempts.
        stop_reason:           Human-readable reason recorded in the kill-switch log.
    """
    logger.warning("=" * 70)
    logger.warning("🚨 CLEAR-AND-RESTART SEQUENCE INITIATED")
    logger.warning("=" * 70)

    # ── Step A: Full emergency reset ─────────────────────────────────────────
    run_emergency_reset(
        brokers=brokers,
        dust_threshold_usd=dust_threshold_usd,
        extra_position_files=extra_position_files,
        stop_reason=stop_reason,
    )

    # ── Step B: Verify positions are cleared ─────────────────────────────────
    if verify_clear and brokers:
        logger.warning("🔍 Verifying all positions are cleared from exchange…")
        cleared = False
        for attempt in range(1, max_verify_attempts + 1):
            try:
                remaining: List = []
                for broker in brokers:
                    try:
                        remaining.extend(broker.get_positions() or [])
                    except Exception as _b_err:
                        logger.debug("Position fetch failed for %s: %s", broker, _b_err)
                if not remaining:
                    logger.warning("✅ All positions confirmed cleared (attempt %d/%d)",
                                   attempt, max_verify_attempts)
                    cleared = True
                    break
                logger.warning(
                    "   ⚠️  %d position(s) still present (attempt %d/%d) — "
                    "waiting %.0fs before re-check…",
                    len(remaining), attempt, max_verify_attempts, verify_wait_s,
                )
                time.sleep(verify_wait_s)
            except Exception as verify_err:
                logger.warning("   Verification attempt %d error: %s", attempt, verify_err)
                time.sleep(verify_wait_s)

        if not cleared:
            logger.error(
                "❌ Could not confirm all positions cleared after %d attempts — "
                "restarting anyway to avoid ghost-position accumulation",
                max_verify_attempts,
            )
    elif verify_clear and not brokers:
        logger.info("   No brokers provided — skipping position verification")

    # ── Step C: Restart the process ──────────────────────────────────────────
    logger.warning("🔄 Restarting NIJA bot process after clearing positions…")
    restart_process()
