"""
NIJA Startup Position Sync
==========================

Synchronises exchange positions with the internal PositionTracker on bot
startup.  Called AFTER all brokers are connected but BEFORE the trading loop
begins so that any holdings that existed before a restart are immediately
visible to exit logic, P&L calculation, and duplicate-entry guards.

Adoption flow per broker
------------------------
1. Obtain the broker's own ``position_tracker`` (each broker holds its own
   ``PositionTracker`` instance backed by ``data/positions.json``).
2. Call ``broker.get_positions()`` — returns non-zero, non-dust holdings.
3. For each position:
   a. If the PositionTracker already has a record for this symbol, skip it
      (the persisted JSON file survived the restart and already has the
      correct entry price).
   b. Attempt to resolve an entry price via three layers:
        i.  ``broker.get_real_entry_price(symbol)`` — trade-history VWAP
        ii. ``EntryPriceStore.get_price(symbol)``   — JSON-backed local store
        iii. ``position['current_price']``           — live market price fallback
   c. Call ``PositionTracker.track_entry(...)`` with
      ``position_source='broker_existing'``.
4. Log ``EXCHANGE_POSITION_SYNC broker=<name> adopted=<count>``.

After all brokers are processed the function logs the total tracked count so
the startup log always contains a definitive ``PositionTracker initialized``
line that reflects reality.

Author: NIJA Trading Systems
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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


def _resolve_entry_price(
    broker: Any,
    symbol: str,
    current_price: float,
    eps: Optional[Any],
) -> float:
    """Resolve the best available entry price for *symbol*.

    Priority:
      1. broker.get_real_entry_price(symbol)  — trade-history VWAP
      2. EntryPriceStore.get_price(symbol)    — persisted local store
      3. current_price                        — live market price fallback
    """
    # Layer 1: broker trade-history VWAP
    if hasattr(broker, "get_real_entry_price"):
        try:
            price = broker.get_real_entry_price(symbol)
            if price and float(price) > 0:
                return float(price)
        except Exception as exc:
            logger.debug(
                "startup_position_sync: get_real_entry_price(%s) failed: %s", symbol, exc
            )

    # Layer 2: local EntryPriceStore
    if eps is not None:
        try:
            stored = eps.get_price(symbol)
            if stored and float(stored) > 0:
                return float(stored)
        except Exception as exc:
            logger.debug(
                "startup_position_sync: EntryPriceStore.get_price(%s) failed: %s", symbol, exc
            )

    # Layer 3: current market price as fallback
    if current_price and float(current_price) > 0:
        logger.debug(
            "startup_position_sync: using current_price=%.6g as entry fallback for %s",
            current_price,
            symbol,
        )
        return float(current_price)

    return 0.0


def _adopt_broker_positions(
    broker: Any,
    broker_name: str,
    eps: Optional[Any],
) -> int:
    """Fetch and adopt open positions from *broker* into its own PositionTracker.

    Each broker (Coinbase, Kraken, OKX) holds its own ``position_tracker``
    attribute backed by ``data/positions.json``.  We write into that instance
    so the rest of the bot (exit logic, P&L, duplicate-entry guards) sees the
    adopted positions through the same object it already uses.

    Returns the number of newly adopted positions.
    """
    tracker = getattr(broker, "position_tracker", None)
    if tracker is None:
        logger.warning(
            "EXCHANGE_POSITION_SYNC broker=%s has no position_tracker — skipping",
            broker_name,
        )
        return 0

    adopted = 0
    try:
        positions: List[Dict] = broker.get_positions()
    except Exception as exc:
        logger.warning(
            "EXCHANGE_POSITION_SYNC broker=%s fetch_failed error=%s",
            broker_name,
            exc,
        )
        return 0

    if not positions:
        logger.info(
            "EXCHANGE_POSITION_SYNC broker=%s adopted=0 (no open positions found)",
            broker_name,
        )
        return 0

    for pos in positions:
        try:
            symbol: str = pos.get("symbol", "")
            quantity: float = float(pos.get("quantity", 0) or 0)
            current_price: float = float(pos.get("current_price", 0) or 0)
            size_usd: float = float(pos.get("size_usd", 0) or 0)

            if not symbol or quantity <= 0:
                continue

            # Skip symbols already tracked — the JSON persistence file survived
            # the restart and already has the correct entry price.
            existing = tracker.get_position(symbol)
            if existing is not None:
                logger.debug(
                    "startup_position_sync: %s already tracked "
                    "(qty=%.8f entry=$%.4f) — skipping",
                    symbol,
                    existing.get("quantity", 0),
                    existing.get("entry_price", 0),
                )
                continue

            # Resolve the best available entry price
            entry_price = _resolve_entry_price(broker, symbol, current_price, eps)

            if entry_price <= 0:
                logger.warning(
                    "startup_position_sync: broker=%s symbol=%s — entry price "
                    "unavailable, adopting with entry_price=0 (will be repaired "
                    "by sync job)",
                    broker_name,
                    symbol,
                )

            # Derive size_usd from entry price when the broker didn't supply it
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

            # Persist to EntryPriceStore so the repair job has a baseline
            if eps is not None and entry_price > 0:
                try:
                    eps.save(symbol, entry_price, source="override", quantity=quantity)
                except Exception as eps_err:
                    logger.debug(
                        "startup_position_sync: EntryPriceStore.save(%s) failed: %s",
                        symbol,
                        eps_err,
                    )

            logger.info(
                "startup_position_sync: adopted %s qty=%.8f entry=$%.4f "
                "size=$%.2f broker=%s",
                symbol,
                quantity,
                entry_price,
                size_usd,
                broker_name,
            )
            adopted += 1

        except Exception as pos_exc:
            logger.warning(
                "startup_position_sync: broker=%s position adoption error "
                "for %r: %s",
                broker_name,
                pos,
                pos_exc,
            )

    logger.info(
        "EXCHANGE_POSITION_SYNC broker=%s adopted=%d",
        broker_name,
        adopted,
    )
    return adopted


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sync_exchange_positions_on_startup(strategy: Any) -> int:
    """Sync open exchange positions into each broker's PositionTracker at startup.

    Must be called AFTER all brokers are connected and BEFORE the trading
    loop starts.  Errors from individual brokers are caught and logged as
    warnings so a single failing broker never blocks the startup sequence.

    Args:
        strategy: The TradingStrategy instance (used to reach platform brokers
                  via ``strategy.multi_account_manager.platform_brokers``).

    Returns:
        Total number of positions newly adopted across all brokers.
    """
    logger.info("EXCHANGE_POSITION_SYNC starting startup position synchronisation")

    eps = _get_entry_price_store()

    # Collect connected platform brokers from the multi-account manager
    platform_brokers: Dict[str, Any] = {}

    mam = getattr(strategy, "multi_account_manager", None)
    if mam is not None:
        try:
            raw_brokers = getattr(mam, "platform_brokers", {}) or {}
            for broker_type, broker in raw_brokers.items():
                if broker is None:
                    continue
                if not getattr(broker, "connected", False):
                    logger.debug(
                        "startup_position_sync: skipping disconnected broker %s",
                        getattr(broker_type, "value", str(broker_type)),
                    )
                    continue
                name = getattr(broker_type, "value", str(broker_type)).lower()
                platform_brokers[name] = broker
        except Exception as exc:
            logger.warning(
                "EXCHANGE_POSITION_SYNC could not read platform_brokers from "
                "multi_account_manager: %s",
                exc,
            )

    # Fallback: try broker_manager directly
    if not platform_brokers:
        bm = getattr(strategy, "broker_manager", None)
        if bm is not None:
            try:
                raw_brokers = getattr(bm, "brokers", {}) or {}
                for broker_type, broker in raw_brokers.items():
                    if broker is None:
                        continue
                    if not getattr(broker, "connected", False):
                        continue
                    name = getattr(broker_type, "value", str(broker_type)).lower()
                    platform_brokers[name] = broker
            except Exception as exc:
                logger.warning(
                    "EXCHANGE_POSITION_SYNC could not read brokers from "
                    "broker_manager: %s",
                    exc,
                )

    if not platform_brokers:
        logger.warning(
            "EXCHANGE_POSITION_SYNC no connected platform brokers found — "
            "position sync skipped"
        )
        return 0

    total_adopted = 0
    for broker_name, broker in platform_brokers.items():
        try:
            count = _adopt_broker_positions(broker, broker_name, eps)
            total_adopted += count
        except Exception as exc:
            logger.warning(
                "EXCHANGE_POSITION_SYNC broker=%s unexpected error: %s",
                broker_name,
                exc,
            )

    # Log the definitive post-sync tracker state across all brokers
    total_tracked = 0
    for broker_name, broker in platform_brokers.items():
        tracker = getattr(broker, "position_tracker", None)
        if tracker is not None:
            try:
                total_tracked += len(tracker.get_all_positions())
            except Exception:
                pass

    logger.info(
        "PositionTracker initialized: %d tracked positions",
        total_tracked,
    )

    return total_adopted
