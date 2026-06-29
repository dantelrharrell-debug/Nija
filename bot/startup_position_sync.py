"""
NIJA Startup Position Sync
==========================

Synchronises exchange positions with the internal PositionTracker on bot
startup. Called AFTER brokers are connected so holdings that existed before a
restart are visible to exit logic, P&L calculation, and duplicate-entry guards.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija")


def _get_entry_price_store() -> Optional[Any]:
    """Return the EntryPriceStore singleton, or None."""
    try:
        from bot.entry_price_store import get_entry_price_store
        return get_entry_price_store()
    except ImportError:
        try:
            from entry_price_store import get_entry_price_store  # type: ignore[import]
            return get_entry_price_store()
        except ImportError:
            return None
    except Exception as exc:
        logger.debug("startup_position_sync: EntryPriceStore unavailable: %s", exc)
        return None


def _resolve_entry_price(broker: Any, symbol: str, current_price: float, eps: Optional[Any]) -> float:
    """Resolve the best available entry price for *symbol*."""
    if hasattr(broker, "get_real_entry_price"):
        try:
            price = broker.get_real_entry_price(symbol)
            if price and float(price) > 0:
                return float(price)
        except Exception as exc:
            logger.debug("startup_position_sync: get_real_entry_price(%s) failed: %s", symbol, exc)

    if eps is not None:
        try:
            stored = eps.get_price(symbol)
            if stored and float(stored) > 0:
                return float(stored)
        except Exception as exc:
            logger.debug("startup_position_sync: EntryPriceStore.get_price(%s) failed: %s", symbol, exc)

    if current_price and float(current_price) > 0:
        return float(current_price)
    return 0.0


def _tracker_count(tracker: Any) -> int:
    if tracker is None:
        return 0
    try:
        positions = tracker.get_all_positions()
        return len(positions or [])
    except Exception:
        return 0


def _adopt_broker_positions(broker: Any, broker_name: str, eps: Optional[Any]) -> int:
    """Fetch and adopt open positions from *broker* into its PositionTracker.

    Guard: ``_startup_position_sync_adopted`` is set on the broker instance
    after the first successful adoption so that repeated calls (e.g. from
    reconnect handlers or multiple startup hooks) are silently skipped.
    """
    # Per-broker idempotency guard: adopt positions at most once per broker
    # instance, regardless of how many times this function is called.
    if getattr(broker, "_startup_position_sync_adopted", False):
        logger.debug(
            "EXCHANGE_POSITION_SYNC broker=%s skipped — already adopted on this instance",
            broker_name,
        )
        return 0
    broker._startup_position_sync_adopted = True

    tracker = getattr(broker, "position_tracker", None)
    if tracker is None:
        logger.warning("EXCHANGE_POSITION_SYNC broker=%s has no position_tracker — skipping", broker_name)
        return 0

    before_count = _tracker_count(tracker)
    try:
        positions: List[Dict] = broker.get_positions()
    except Exception as exc:
        logger.warning("EXCHANGE_POSITION_SYNC broker=%s fetch_failed error=%s", broker_name, exc)
        return 0

    fetched_count = len(positions or [])
    logger.info(
        "EXCHANGE_POSITION_SYNC broker=%s fetched=%d tracked_before=%d connected=%s",
        broker_name,
        fetched_count,
        before_count,
        getattr(broker, "connected", None),
    )

    if not positions:
        logger.info("EXCHANGE_POSITION_SYNC broker=%s adopted=0 skipped_existing=0 skipped_invalid=0 reason=no_open_positions", broker_name)
        return 0

    adopted = 0
    skipped_existing = 0
    skipped_invalid = 0
    skipped_errors = 0

    for pos in positions:
        try:
            symbol = str(pos.get("symbol", "") or "").strip()
            quantity = float(pos.get("quantity", 0) or 0)
            current_price = float(pos.get("current_price", 0) or 0)
            size_usd = float(pos.get("size_usd", 0) or 0)

            if not symbol or quantity <= 0:
                skipped_invalid += 1
                logger.info(
                    "EXCHANGE_POSITION_SYNC broker=%s skip_invalid symbol=%r quantity=%s raw=%r",
                    broker_name,
                    symbol,
                    quantity,
                    pos,
                )
                continue

            existing = tracker.get_position(symbol)
            if existing is not None:
                skipped_existing += 1
                logger.info(
                    "EXCHANGE_POSITION_SYNC broker=%s skip_existing symbol=%s qty=%.8f entry=$%.4f",
                    broker_name,
                    symbol,
                    float(existing.get("quantity", 0) or 0),
                    float(existing.get("entry_price", 0) or 0),
                )
                continue

            entry_price = _resolve_entry_price(broker, symbol, current_price, eps)
            if entry_price <= 0:
                logger.warning(
                    "EXCHANGE_POSITION_SYNC broker=%s symbol=%s entry_price_unavailable current_price=%.8f adopting_for_repair",
                    broker_name,
                    symbol,
                    current_price,
                )

            if size_usd <= 0 and entry_price > 0:
                size_usd = quantity * entry_price

            tracker.track_entry(
                symbol=symbol,
                entry_price=entry_price,
                quantity=quantity,
                size_usd=size_usd,
                strategy="STARTUP_SYNC",
                position_source="broker_existing",
            )

            if eps is not None and entry_price > 0:
                try:
                    eps.save(symbol, entry_price, source="override", quantity=quantity)
                except Exception as eps_err:
                    logger.debug("startup_position_sync: EntryPriceStore.save(%s) failed: %s", symbol, eps_err)

            logger.info(
                "EXCHANGE_POSITION_SYNC broker=%s adopted_symbol=%s qty=%.8f entry=$%.4f size=$%.2f",
                broker_name,
                symbol,
                quantity,
                entry_price,
                size_usd,
            )
            adopted += 1
        except Exception as pos_exc:
            skipped_errors += 1
            logger.warning("EXCHANGE_POSITION_SYNC broker=%s position_adoption_error raw=%r error=%s", broker_name, pos, pos_exc)

    after_count = _tracker_count(tracker)
    logger.info(
        "EXCHANGE_POSITION_SYNC broker=%s fetched=%d adopted=%d skipped_existing=%d skipped_invalid=%d skipped_errors=%d tracked_before=%d tracked_after=%d",
        broker_name,
        fetched_count,
        adopted,
        skipped_existing,
        skipped_invalid,
        skipped_errors,
        before_count,
        after_count,
    )
    return adopted


def _broker_name(broker_type: Any, *, prefix: str = "") -> str:
    raw = getattr(broker_type, "value", str(broker_type)).lower()
    return f"{prefix}{raw}" if prefix else raw


def _collect_connected_brokers(strategy: Any) -> Dict[str, Any]:
    """Collect connected platform and user brokers from MABM and BrokerManager."""
    brokers: Dict[str, Any] = {}
    mam = getattr(strategy, "multi_account_manager", None)

    if mam is not None:
        try:
            raw_platform = getattr(mam, "platform_brokers", {}) or {}
            for broker_type, broker in raw_platform.items():
                if broker is not None and getattr(broker, "connected", False):
                    brokers[_broker_name(broker_type, prefix="platform:")] = broker
        except Exception as exc:
            logger.warning("EXCHANGE_POSITION_SYNC could not read platform_brokers from multi_account_manager: %s", exc)

        try:
            raw_users = getattr(mam, "user_brokers", {}) or {}
            for user_id, user_broker_dict in raw_users.items():
                for broker_type, broker in (user_broker_dict or {}).items():
                    if broker is not None and getattr(broker, "connected", False):
                        brokers[_broker_name(broker_type, prefix=f"user:{user_id}:")] = broker
        except Exception as exc:
            logger.warning("EXCHANGE_POSITION_SYNC could not read user_brokers from multi_account_manager: %s", exc)

    bm = getattr(strategy, "broker_manager", None)
    if bm is not None:
        try:
            raw_brokers = getattr(bm, "brokers", {}) or {}
            for broker_type, broker in raw_brokers.items():
                if broker is not None and getattr(broker, "connected", False):
                    name = _broker_name(broker_type, prefix="broker_manager:")
                    brokers.setdefault(name, broker)
        except Exception as exc:
            logger.warning("EXCHANGE_POSITION_SYNC could not read brokers from broker_manager: %s", exc)

    return brokers


def sync_exchange_positions_on_startup(strategy: Any) -> int:
    """Sync open exchange positions into each connected broker's PositionTracker.

    Guard: ``_startup_position_sync_done`` is checked on the strategy instance
    so that this function is idempotent even when called directly (i.e. without
    going through ``_invoke_position_sync`` in startup_runtime_safety).  The
    flag is set before any broker work begins so re-entrant calls are no-ops.
    """
    # Defense-in-depth guard: the primary guard lives in _invoke_position_sync
    # (startup_runtime_safety.py), but protect here too so direct callers are
    # also safe from double-execution.
    if getattr(strategy, "_startup_position_sync_done", False):
        logger.debug("EXCHANGE_POSITION_SYNC skipped — already completed for this strategy instance")
        return 0
    # Do NOT set _startup_position_sync_done here — that flag is owned by
    # _invoke_position_sync.  Setting it here would prevent the caller's guard
    # from seeing the correct state.  Per-broker deduplication is handled by
    # _adopt_broker_positions via _startup_position_sync_adopted.

    logger.info("EXCHANGE_POSITION_SYNC starting startup position synchronisation")

    eps = _get_entry_price_store()
    connected_brokers = _collect_connected_brokers(strategy)

    logger.info(
        "EXCHANGE_POSITION_SYNC connected_broker_count=%d brokers=%s",
        len(connected_brokers),
        sorted(connected_brokers.keys()),
    )

    if not connected_brokers:
        logger.warning("EXCHANGE_POSITION_SYNC no connected brokers found — position sync skipped")
        return 0

    total_adopted = 0
    for broker_name, broker in connected_brokers.items():
        try:
            total_adopted += _adopt_broker_positions(broker, broker_name, eps)
        except Exception as exc:
            logger.warning("EXCHANGE_POSITION_SYNC broker=%s unexpected error: %s", broker_name, exc)

    total_tracked = 0
    tracker_seen: set[int] = set()
    for broker in connected_brokers.values():
        tracker = getattr(broker, "position_tracker", None)
        if tracker is not None and id(tracker) not in tracker_seen:
            tracker_seen.add(id(tracker))
            total_tracked += _tracker_count(tracker)

    logger.info(
        "EXCHANGE_POSITION_SYNC complete connected_brokers=%d adopted_total=%d total_tracked=%d",
        len(connected_brokers),
        total_adopted,
        total_tracked,
    )
    logger.info("PositionTracker initialized: %d tracked positions", total_tracked)
    return total_adopted
