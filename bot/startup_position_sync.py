"""Synchronize exchange positions into account-scoped position trackers.

Broker snapshots are authoritative for quantity. They are reconciled exactly and
must never be treated as additive fills.

The position fetch itself is bounded by the v95 startup handoff.  Entry-price
reconstruction is a separate broker read, though, and historically remained
unbounded.  A slow fill-history lookup could therefore hold the entire startup
reconciliation after an authoritative quantity snapshot had already returned,
preventing later brokers from being inspected.  The v279 path below bounds those
read-only cost-basis lookups with a per-broker/symbol single flight.  A timeout
never substitutes current market price and never marks a broker synchronized.
Late results remain reusable by a later authoritative retry.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija")
_LAST_COMPLETED_STRATEGY: Any = None

_ENTRY_PRICE_BOUND_MARKER = "20260829-position-entry-price-bound-v279"
_DUST_SYNC_MARKER = "20260905-startup-dust-adoption-v371"
_ENTRY_PRICE_FLIGHT_LOCK = threading.RLock()
_ENTRY_PRICE_FLIGHTS: Dict[Tuple[int, str], Dict[str, Any]] = {}


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


def _entry_price_timeout_s() -> float:
    try:
        return max(
            0.25,
            float(os.environ.get("NIJA_POSITION_ENTRY_PRICE_TIMEOUT_S", "5") or 5.0),
        )
    except (TypeError, ValueError):
        return 5.0


def _finish_entry_price_flight(
    flight: Dict[str, Any],
    method: Any,
    symbol: str,
) -> None:
    try:
        flight["result"] = method(symbol)
    except BaseException as exc:
        flight["error"] = exc
    finally:
        flight["finished_at"] = time.monotonic()
        flight["event"].set()


def _bounded_real_entry_price(broker: Any, symbol: str) -> Tuple[float, str]:
    """Read broker-native entry price without allowing startup to block forever.

    The call is read-only.  One worker is retained per broker/symbol until its
    result is consumed, so a timeout does not create duplicate fill-history
    requests.  A timeout/error returns no price; callers may still use other
    already-verified cost-basis sources but must never substitute market price.
    """

    method = getattr(broker, "get_real_entry_price", None)
    if not callable(method):
        return 0.0, "api_unavailable"

    normalized_symbol = str(symbol or "").strip().upper()
    key = (id(broker), normalized_symbol)
    started_new = False
    with _ENTRY_PRICE_FLIGHT_LOCK:
        flight = _ENTRY_PRICE_FLIGHTS.get(key)
        if flight is None:
            event = threading.Event()
            flight = {
                "event": event,
                "result": None,
                "error": None,
                "started_at": time.monotonic(),
                "finished_at": 0.0,
            }
            _ENTRY_PRICE_FLIGHTS[key] = flight
            worker = threading.Thread(
                target=_finish_entry_price_flight,
                args=(flight, method, symbol),
                name=f"position-entry-price-v279-{type(broker).__name__}-{normalized_symbol}",
                daemon=True,
            )
            flight["thread"] = worker
            worker.start()
            started_new = True

    timeout_s = _entry_price_timeout_s()
    if not flight["event"].wait(timeout=timeout_s):
        age_s = max(
            0.0,
            time.monotonic() - float(flight.get("started_at", 0.0) or 0.0),
        )
        logger.warning(
            "POSITION_ENTRY_PRICE_V279_TIMEOUT marker=%s broker=%s symbol=%s "
            "timeout_s=%.2f age_s=%.2f single_flight_reused=%s "
            "authoritative_cost_basis_unresolved=true synthetic_entry=false "
            "current_price_fallback=false",
            _ENTRY_PRICE_BOUND_MARKER,
            type(broker).__name__,
            symbol,
            timeout_s,
            age_s,
            str(not started_new).lower(),
        )
        return 0.0, "api_timeout"

    error = flight.get("error")
    result = flight.get("result")
    with _ENTRY_PRICE_FLIGHT_LOCK:
        if _ENTRY_PRICE_FLIGHTS.get(key) is flight:
            _ENTRY_PRICE_FLIGHTS.pop(key, None)

    if error is not None:
        logger.warning(
            "POSITION_ENTRY_PRICE_V279_ERROR marker=%s broker=%s symbol=%s "
            "error=%s:%s authoritative_cost_basis_unresolved=true synthetic_entry=false",
            _ENTRY_PRICE_BOUND_MARKER,
            type(broker).__name__,
            symbol,
            type(error).__name__,
            error,
        )
        return 0.0, "api_error"

    price = _safe_float(result)
    if price > 0:
        return price, "api"
    return 0.0, "api_empty"


def _position_payload_entry_price(
    position: Optional[Dict],
    broker_quantity: float,
) -> Tuple[float, str]:
    """Return broker-native cost basis carried by the position payload."""

    if not isinstance(position, dict):
        return 0.0, ""
    for key in (
        "entry_price",
        "average_entry_price",
        "avg_entry_price",
        "avg_price",
        "cost_basis_price",
    ):
        price = _safe_float(position.get(key))
        if price > 0:
            return price, "broker_position"
    for key in ("cost_basis", "cost_basis_usd", "total_cost", "executed_cost"):
        total_cost = _safe_float(position.get(key))
        if total_cost > 0 and broker_quantity > 0:
            return total_cost / broker_quantity, "broker_position"
    return 0.0, ""


def _legacy_duplicate_snapshot_detected(
    existing: Optional[Dict],
    broker_quantity: float,
) -> bool:
    """Detect cost-basis dilution caused by additive broker snapshot ingestion."""
    if not existing or broker_quantity <= 0:
        return False
    existing_qty = _safe_float(existing.get("quantity"))
    existing_cost = _safe_float(existing.get("size_usd"))
    num_adds = int(_safe_float(existing.get("num_adds")))
    strategy = str(existing.get("strategy", "") or "").strip().upper()
    position_source = str(existing.get("position_source", "") or "").strip().lower()
    quantity_error = abs(existing_qty - broker_quantity) / max(broker_quantity, 1e-12)
    startup_owned = strategy == "STARTUP_SYNC" or position_source == "broker_existing"
    return (
        existing_qty > 0
        and existing_cost > 0
        and num_adds > 0
        and startup_owned
        and quantity_error > 0.05
    )


def _resolve_entry_price(
    broker: Any,
    symbol: str,
    eps: Optional[Any],
    broker_quantity: float,
    existing: Optional[Dict] = None,
    position: Optional[Dict] = None,
) -> Tuple[float, str]:
    """Resolve cost basis from broker-native evidence, never from market price."""

    payload_price, payload_source = _position_payload_entry_price(
        position,
        broker_quantity,
    )
    if payload_price > 0:
        return payload_price, payload_source

    api_source = ""
    if hasattr(broker, "get_real_entry_price"):
        price, api_source = _bounded_real_entry_price(broker, symbol)
        if price > 0:
            return price, "api"

    # Old startup sync treated every broker snapshot as a new fill. The diluted
    # average was then persisted with the default "execution" source and no
    # quantity, so source alone cannot prove the record is trustworthy. When the
    # tracker carries the duplicate-sync signature, force exact snapshot repair
    # to reconstruct entry from stored cost basis / actual broker quantity.
    if _legacy_duplicate_snapshot_detected(existing, broker_quantity):
        existing_qty = _safe_float((existing or {}).get("quantity"))
        existing_cost = _safe_float((existing or {}).get("size_usd"))
        reconstructed = existing_cost / broker_quantity if broker_quantity > 0 else 0.0
        logger.warning(
            "EXCHANGE_POSITION_SYNC legacy_diluted_entry_ignored symbol=%s "
            "tracked_qty=%.8f broker_qty=%.8f stored_cost=$%.8f reconstructed_entry=$%.8f",
            symbol,
            existing_qty,
            broker_quantity,
            existing_cost,
            reconstructed,
        )
        return 0.0, "reconstructed_cost_basis"

    if eps is not None:
        try:
            record = eps.get(symbol) if callable(getattr(eps, "get", None)) else None
            stored = _safe_float(getattr(record, "price", None))
            source = str(getattr(record, "source", "override") or "override")
            stored_qty = _safe_float(getattr(record, "quantity", 0.0))
            verified_sources = {
                "execution", "api", "trade_history", "closed_orders", "fills",
                "broker_position", "reconstructed_verified_cost_basis",
            }
            if stored > 0 and source.strip().lower() in verified_sources:
                if stored_qty > 0 and broker_quantity > 0:
                    relative_qty_error = abs(stored_qty - broker_quantity) / max(broker_quantity, 1e-12)
                    if relative_qty_error > 0.05:
                        logger.warning(
                            "EXCHANGE_POSITION_SYNC stale_verified_record_ignored "
                            "symbol=%s stored_qty=%.8f broker_qty=%.8f source=%s",
                            symbol,
                            stored_qty,
                            broker_quantity,
                            source,
                        )
                    else:
                        return stored, source
                else:
                    return stored, source
        except Exception as exc:
            logger.debug("startup_position_sync: EntryPriceStore lookup failed for %s: %s", symbol, exc)

    return 0.0, api_source or "override"


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


def _policy_dust_excluded(position: Optional[Dict]) -> bool:
    """Return true only for a row fully classified by NIJA's canonical dust policy.

    Dust rows remain visible and unverified; they simply do not require cost-basis
    reconciliation or protective exits.  Requiring every exclusion flag prevents
    a partial/malformed classification from weakening startup fail-closed behavior.
    """
    return bool(
        isinstance(position, dict)
        and str(position.get("classification", "") or "").strip().upper() == "DUST"
        and position.get("exclude_from_reconciliation") is True
        and position.get("exclude_from_auto_exit") is True
        and position.get("exclude_from_strategy") is True
        and position.get("exclude_from_position_limit") is True
    )


def _adopt_broker_positions(broker: Any, broker_name: str, eps: Optional[Any]) -> int:
    """Fetch and exactly reconcile open positions for one broker."""
    tracker = getattr(broker, "position_tracker", None)
    if tracker is None:
        setattr(broker, "_startup_position_sync_adopted", False)
        logger.warning("EXCHANGE_POSITION_SYNC broker=%s has no position_tracker — skipping", broker_name)
        return 0

    before_count = _tracker_count(tracker)
    try:
        raw_positions = broker.get_positions()
    except Exception as exc:
        setattr(broker, "_startup_position_sync_adopted", False)
        logger.warning("EXCHANGE_POSITION_SYNC broker=%s fetch_failed error=%s", broker_name, exc)
        return 0

    # Only an explicit list can prove an authoritative broker snapshot.  None,
    # dicts, generators, and other unexpected payloads must not be reclassified
    # as an empty account.
    if not isinstance(raw_positions, list):
        setattr(broker, "_startup_position_sync_adopted", False)
        setattr(broker, "_startup_position_sync_symbols", tuple())
        logger.critical(
            "EXCHANGE_POSITION_SYNC_INVALID_SNAPSHOT marker=%s broker=%s payload_type=%s "
            "authoritative_empty=false position_snapshot_fail_closed=true "
            "synthetic_empty_snapshot=false",
            _ENTRY_PRICE_BOUND_MARKER,
            broker_name,
            type(raw_positions).__name__,
        )
        return 0

    positions: List[Dict] = list(raw_positions)
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
        # Empty snapshots are valid only because get_positions returned an
        # explicit list successfully in this exact call.
        setattr(broker, "_startup_position_sync_adopted", True)
        setattr(broker, "_startup_position_sync_symbols", tuple())
        return 0

    reconciled = 0
    unchanged = 0
    skipped_invalid = 0
    errors = 0
    successful_symbols: list[str] = []
    dust_excluded_symbols: list[str] = []

    for pos in positions:
        try:
            if not isinstance(pos, dict):
                skipped_invalid += 1
                errors += 1
                logger.warning(
                    "EXCHANGE_POSITION_SYNC broker=%s invalid_position_payload type=%s "
                    "position_snapshot_fail_closed=true",
                    broker_name,
                    type(pos).__name__,
                )
                continue
            symbol = str(pos.get("symbol", "") or "").strip()
            quantity = _safe_float(pos.get("quantity", pos.get("size", 0.0)))
            current_price = _safe_float(pos.get("current_price", pos.get("price", 0.0)))
            broker_value = _safe_float(pos.get("size_usd", pos.get("market_value", 0.0)))
            if not symbol or quantity <= 0:
                skipped_invalid += 1
                errors += 1
                logger.warning(
                    "EXCHANGE_POSITION_SYNC broker=%s skip_invalid symbol=%r quantity=%s "
                    "position_snapshot_fail_closed=true raw=%r",
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
                existing,
                position=pos,
            )
            changed = _position_changed(existing, quantity, entry_price)

            exact_sync = getattr(tracker, "sync_position_snapshot", None)
            if callable(exact_sync):
                # exact_sync may retain an unverified quantity snapshot for
                # visibility. That is useful, but it must not count as startup
                # adoption until cost basis is genuinely verified, except for a
                # row that the canonical dust policy explicitly excludes from
                # reconciliation and auto-exit requirements.
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
            elif existing is None and entry_price > 0:
                # Never use current market price or broker market value as a
                # substitute for historical cost basis.
                cost_basis = quantity * entry_price
                ok = bool(
                    tracker.track_entry(
                        symbol=symbol,
                        entry_price=entry_price,
                        quantity=quantity,
                        size_usd=cost_basis,
                        strategy="STARTUP_SYNC",
                        position_source="broker_existing",
                    )
                )
            else:
                logger.error(
                    "EXCHANGE_POSITION_SYNC broker=%s exact_sync_unavailable symbol=%s "
                    "verified_entry_available=%s current_price_fallback=false "
                    "existing_position_not_modified=%s",
                    broker_name,
                    symbol,
                    entry_price > 0,
                    existing is not None,
                )
                ok = False

            if not ok:
                errors += 1
                continue

            final_position = tracker.get_position(symbol) if callable(getattr(tracker, "get_position", None)) else None
            cost_basis_verified = bool(
                isinstance(final_position, dict)
                and final_position.get("cost_basis_verified") is True
                and _safe_float(final_position.get("entry_price")) > 0
            )
            if not cost_basis_verified and _policy_dust_excluded(final_position):
                dust_excluded_symbols.append(symbol)
                if changed:
                    reconciled += 1
                else:
                    unchanged += 1
                logger.critical(
                    "POSITION_SYNC_DUST_POLICY_V371_RESOLVED marker=%s broker=%s symbol=%s "
                    "qty=%.8f current=$%.8f broker_value=$%.8f classification=DUST "
                    "quantity_snapshot_adopted=true cost_basis_verified=false "
                    "protective_exit_required=false auto_exit_blocked_unchanged=true "
                    "position_visible=true entry_price_fabricated=false "
                    "protective_exit_fabricated=false safety_gates_bypassed=false",
                    _DUST_SYNC_MARKER,
                    broker_name,
                    symbol,
                    quantity,
                    current_price,
                    broker_value,
                )
                continue

            if not cost_basis_verified:
                errors += 1
                logger.critical(
                    "POSITION_SYNC_COST_BASIS_UNVERIFIED marker=%s broker=%s symbol=%s "
                    "qty=%.8f entry_source=%s broker_value=$%.2f quantity_visible=true "
                    "startup_position_adopted=false protective_exit_basis_unproven=true "
                    "auto_exit_blocked=%s synthetic_entry=false current_price_fallback=false",
                    _ENTRY_PRICE_BOUND_MARKER,
                    broker_name,
                    symbol,
                    quantity,
                    entry_source,
                    broker_value,
                    bool((final_position or {}).get("auto_exit_blocked", True)),
                )
                continue

            successful_symbols.append(symbol)
            if changed:
                reconciled += 1
            else:
                unchanged += 1
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
    resolved_symbols = list(dict.fromkeys(successful_symbols + dust_excluded_symbols))
    fully_synced = bool(
        len(resolved_symbols) == len(positions)
        and errors == 0
        and skipped_invalid == 0
    )
    setattr(broker, "_startup_position_sync_adopted", fully_synced)
    setattr(broker, "_startup_position_sync_symbols", tuple(sorted(resolved_symbols)))
    setattr(broker, "_startup_position_sync_dust_symbols_v371", tuple(sorted(dust_excluded_symbols)))
    logger.info(
        "EXCHANGE_POSITION_SYNC broker=%s fetched=%d reconciled=%d unchanged=%d skipped_invalid=%d errors=%d "
        "tracked_before=%d tracked_after=%d marked_synced=%s verified_symbols=%d dust_excluded=%d resolved_symbols=%d/%d",
        broker_name,
        len(positions),
        reconciled,
        unchanged,
        skipped_invalid,
        errors,
        before_count,
        after_count,
        fully_synced,
        len(successful_symbols),
        len(dust_excluded_symbols),
        len(resolved_symbols),
        len(positions),
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
    global _LAST_COMPLETED_STRATEGY
    _LAST_COMPLETED_STRATEGY = None
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
    _LAST_COMPLETED_STRATEGY = strategy
    logger.critical(
        "EXCHANGE_POSITION_SYNC_DISPATCH_STRATEGY_READY type=%s connected_brokers=%d total_tracked=%d",
        type(strategy).__name__,
        len(connected_brokers),
        total_tracked,
    )
    logger.info("PositionTracker initialized: %d tracked positions", total_tracked)
    return total_reconciled


__all__ = [
    "sync_exchange_positions_on_startup",
    "_adopt_broker_positions",
    "_bounded_real_entry_price",
    "_collect_connected_brokers",
    "_entry_price_timeout_s",
    "_legacy_duplicate_snapshot_detected",
    "_policy_dust_excluded",
    "_LAST_COMPLETED_STRATEGY",
]
