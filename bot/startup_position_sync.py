"""Synchronize exchange positions into account-scoped position trackers.

Broker snapshots are authoritative for quantity. They are reconciled exactly and
must never be treated as additive fills.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija")


def _get_entry_price_store() -> Optional[Any]:
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed == parsed else default


def _resolve_entry_price(
    broker: Any,
    symbol: str,
    eps: Optional[Any],
    broker_quantity: float,
) -> Tuple[float, str]:
    """Resolve a trustworthy cost-basis price without using current market price."""
    if hasattr(broker, "get_real_entry_price"):
        try:
            price = _safe_float(broker.get_real_entry_price(symbol))
            if price > 0:
                return price, "api"
        except Exception as exc:
            logger.debug("startup_position_sync: get_real_entry_price(%s) failed: %s", symbol, exc)

    if eps is not None:
        try:
            record = eps.get(symbol) if callable(getattr(eps, "get", None)) else None
            stored = _safe_float(getattr(record, "price", None))
            source = str(getattr(record, "source", "override") or "override")
            stored_qty = _safe_float(getattr(record, "quantity", 0.0))
            if stored > 0:
                # Execution/API prices remain useful even if the held quantity
                # changed. Override prices with a mismatched quantity may be the
                # product of the old duplicate-snapshot bug, so let the tracker
                # reconstruct cost basis instead of trusting them blindly.
                if source in {"execution", "api"}:
                    return stored, source
                if stored_qty <= 0 or broker_quantity <= 0:
                    return stored, source
                relative_qty_error = abs(stored_qty - broker_quantity) / max(broker_quantity, 1e-12)
                if relative_qty_error <= 0.05:
                    return stored, source
                logger.warning(
                    "EXCHANGE_POSITION_SYNC stale_override_ignored symbol=%s stored_qty=%.8f broker_qty=%.8f",
                    symbol,
                    stored_qty,
                    broker_quantity,
                )
        except Exception as exc:
            logger.debug("startup_position_sync: EntryPriceStore lookup failed for %s: %s", symbol, exc)

    return 0.0, "override"


def _tracker_count(tracker: Any) -> int:
    if tracker is None:
        return 0
    try:
        positions = tracker.get_all_positions()
        return len(positions or [])
    except Exception:
        return 0


def _position_changed(existing: Optional[Dict], quantity: float, entry_price: float) -> bool:
    if existing is None:
        return True
    old_qty = _safe_float(existing.get("quantity"))
    old_entry = _safe_float(existing.get("entry_price"))
    qty_changed = abs(old_qty - quantity) > max(1e-10, quantity * 1e-8)
    entry_changed = entry_price > 0 and abs(old_entry - entry_price) > max(1e-8, entry_price * 1e-8)
    return qty_changed or entry_changed


def _adopt_broker_positions(broker: Any, broker_name: str, eps: Optional[Any]) -> int:
    """Fetch and exactly reconcile open positions for one broker."""
    tracker = getattr(broker, "position_tracker", None)
    if tracker is None:
        logger.warning("EXCHANGE_POSITION_SYNC broker=%s has no position_tracker — skipping", broker_name)
        return 0

    before_count = _tracker_count(tracker)
    try:
        raw_positions = broker.get_positions()
        positions: List[Dict] = list(raw_positions or []) if isinstance(raw_positions, list) else []
    except Exception as exc:
        logger.warning("EXCHANGE_POSITION_SYNC broker=%s fetch_failed error=%s", broker_name, exc)
        return 0

    logger.info(
        "EXCHANGE_POSITION_SYNC broker=%s fetched=%d tracked_before=%d connected=%s previously_synced=%s",
        broker_name,
        len(positions),
        before_count,
        getattr(broker, "connected", None),
        getattr(broker, "_startup_position_sync_adopted", False),
    )

    if not positions:
        logger.info(
            "EXCHANGE_POSITION_SYNC broker=%s reconciled=0 skipped_invalid=0 errors=0 reason=no_open_positions",
            broker_name,
        )
        # A broker may connect before balances hydrate. Keep it retryable.
        setattr(broker, "_startup_position_sync_adopted", False)
        return 0

    reconciled = 0
    unchanged = 0
    skipped_invalid = 0
    errors = 0
    successful_symbols: list[str] = []

    for pos in positions:
        try:
            if not isinstance(pos, dict):
                skipped_invalid += 1
                continue
            symbol = str(pos.get("symbol", "") or "").strip()
            quantity = _safe_float(pos.get("quantity", pos.get("size", 0.0)))
            current_price = _safe_float(pos.get("current_price", pos.get("price", 0.0)))
            broker_value = _safe_float(pos.get("size_usd", pos.get("market_value", 0.0)))
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

            existing = tracker.get_position(symbol) if callable(getattr(tracker, "get_position", None)) else None
            entry_price, entry_source = _resolve_entry_price(
                broker,
                symbol,
                eps,
                quantity,
            )
            changed = _position_changed(existing, quantity, entry_price)

            exact_sync = getattr(tracker, "sync_position_snapshot", None)
            if callable(exact_sync):
                ok = bool(
                    exact_sync(
                        symbol=symbol,
                        quantity=quantity,
                        entry_price=entry_price,
                        current_price=current_price,
                        size_usd=broker_value,
                        strategy="STARTUP_SYNC",
                        position_source="broker_existing",
                        entry_price_source=entry_source,
                    )
                )
            elif existing is None:
                # Legacy fallback only for a new position. Never call additive
                # track_entry for an existing broker snapshot.
                fallback_entry = entry_price or current_price
                cost_basis = quantity * fallback_entry if fallback_entry > 0 else broker_value
                ok = bool(
                    tracker.track_entry(
                        symbol=symbol,
                        entry_price=fallback_entry,
                        quantity=quantity,
                        size_usd=cost_basis,
                        strategy="STARTUP_SYNC",
                        position_source="broker_existing",
                    )
                )
            else:
                logger.error(
                    "EXCHANGE_POSITION_SYNC broker=%s exact_sync_unavailable symbol=%s existing_position_not_modified",
                    broker_name,
                    symbol,
                )
                ok = False

            if not ok:
                errors += 1
                continue

            successful_symbols.append(symbol)
            if changed:
                reconciled += 1
            else:
                unchanged += 1
            final_position = tracker.get_position(symbol) if callable(getattr(tracker, "get_position", None)) else None
            logger.info(
                "EXCHANGE_POSITION_SYNC broker=%s synced_symbol=%s qty=%.8f entry=$%.8f current=$%.8f broker_value=$%.2f changed=%s",
                broker_name,
                symbol,
                quantity,
                _safe_float((final_position or {}).get("entry_price", entry_price)),
                current_price,
                broker_value,
                changed,
            )
        except Exception as exc:
            errors += 1
            logger.warning(
                "EXCHANGE_POSITION_SYNC broker=%s position_reconcile_error raw=%r error=%s",
                broker_name,
                pos,
                exc,
            )

    after_count = _tracker_count(tracker)
    fully_synced = bool(successful_symbols) and errors == 0
    setattr(broker, "_startup_position_sync_adopted", fully_synced)
    setattr(broker, "_startup_position_sync_symbols", tuple(sorted(successful_symbols)))
    logger.info(
        "EXCHANGE_POSITION_SYNC broker=%s fetched=%d reconciled=%d unchanged=%d skipped_invalid=%d errors=%d "
        "tracked_before=%d tracked_after=%d marked_synced=%s",
        broker_name,
        len(positions),
        reconciled,
        unchanged,
        skipped_invalid,
        errors,
        before_count,
        after_count,
        fully_synced,
    )
    return reconciled


def _broker_name(broker_type: Any, *, prefix: str = "") -> str:
    raw = getattr(broker_type, "value", str(broker_type)).lower()
    return f"{prefix}{raw}" if prefix else raw


def _collect_connected_brokers(strategy: Any) -> Dict[str, Any]:
    brokers: Dict[str, Any] = {}
    mam = getattr(strategy, "multi_account_manager", None)

    if mam is not None:
        try:
            for broker_type, broker in (getattr(mam, "platform_brokers", {}) or {}).items():
                if broker is not None and getattr(broker, "connected", False):
                    brokers[_broker_name(broker_type, prefix="platform:")] = broker
        except Exception as exc:
            logger.warning("EXCHANGE_POSITION_SYNC could not read platform_brokers: %s", exc)

        try:
            for user_id, user_broker_dict in (getattr(mam, "user_brokers", {}) or {}).items():
                for broker_type, broker in (user_broker_dict or {}).items():
                    if broker is not None and getattr(broker, "connected", False):
                        brokers[_broker_name(broker_type, prefix=f"user:{user_id}:")] = broker
        except Exception as exc:
            logger.warning("EXCHANGE_POSITION_SYNC could not read user_brokers: %s", exc)

    bm = getattr(strategy, "broker_manager", None)
    if bm is not None:
        try:
            for broker_type, broker in (getattr(bm, "brokers", {}) or {}).items():
                if broker is not None and getattr(broker, "connected", False):
                    brokers.setdefault(_broker_name(broker_type, prefix="broker_manager:"), broker)
        except Exception as exc:
            logger.warning("EXCHANGE_POSITION_SYNC could not read broker_manager brokers: %s", exc)

    return brokers


def sync_exchange_positions_on_startup(strategy: Any) -> int:
    """Reconcile every currently connected platform and user broker."""
    logger.info("EXCHANGE_POSITION_SYNC starting startup position synchronisation")
    eps = _get_entry_price_store()
    connected_brokers = _collect_connected_brokers(strategy)
    logger.info(
        "EXCHANGE_POSITION_SYNC connected_broker_count=%d brokers=%s",
        len(connected_brokers),
        sorted(connected_brokers.keys()),
    )
    if not connected_brokers:
        logger.warning("EXCHANGE_POSITION_SYNC no connected brokers found — retry will remain eligible")
        return 0

    total_reconciled = 0
    for broker_name, broker in connected_brokers.items():
        try:
            total_reconciled += _adopt_broker_positions(broker, broker_name, eps)
        except Exception as exc:
            logger.warning("EXCHANGE_POSITION_SYNC broker=%s unexpected error: %s", broker_name, exc)

    total_tracked = 0
    tracker_seen: set[int] = set()
    for broker in connected_brokers.values():
        tracker = getattr(broker, "position_tracker", None)
        if tracker is not None and id(tracker) not in tracker_seen:
            tracker_seen.add(id(tracker))
            total_tracked += _tracker_count(tracker)

    synced_brokers = sum(
        1 for broker in connected_brokers.values() if getattr(broker, "_startup_position_sync_adopted", False)
    )
    logger.info(
        "EXCHANGE_POSITION_SYNC complete connected_brokers=%d synced_brokers=%d reconciled_total=%d total_tracked=%d",
        len(connected_brokers),
        synced_brokers,
        total_reconciled,
        total_tracked,
    )
    logger.info("PositionTracker initialized: %d tracked positions", total_tracked)
    return total_reconciled


__all__ = [
    "sync_exchange_positions_on_startup",
    "_adopt_broker_positions",
    "_collect_connected_brokers",
]
