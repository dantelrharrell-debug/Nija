"""Authenticated recovery of NIJA's previously verified Kraken execution probe.

This is a read-only liveness fallback. A historical order id is only a candidate;
proof still requires an exact authenticated Kraken QueryOrders row in a final
state with positive executed volume and positive cost. The authenticated row is
then handed to the existing v357/v328/v346 proof chain.

v406c broadens broker discovery to the authoritative v367 account-broker registry
in addition to v363's multi-account list. This fixes startup/runtime cases where
v367 can already see a connected Kraken account while v363's list is temporarily
empty or incomplete. Brokers are deduplicated and all existing proof criteria
remain unchanged.

No order is submitted/cancelled, no remembered fill is promoted, and no writer,
nonce, risk, capital, position, kill-switch, activation or protective-exit gate
is changed or bypassed.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import threading
import time
from collections.abc import Mapping
from typing import Any

LOGGER = logging.getLogger("nija.runtime_known_execution_probe_revalidation_v406")
MARKER = "20260910-runtime-known-execution-probe-revalidation-v406c"
_READY_FLAG = "NIJA_RUNTIME_KNOWN_EXECUTION_PROBE_REVALIDATION_V406_READY"
_FALLBACK_ORDER_ID = "OSW7F3-YD2NX-SR3BZB"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
# Authenticated closed orders whose genuine broker close time has expired do not
# qualify for the preactivation 1,800-second execution-proof gate.  Cache only
# this broker-verified historical outcome to avoid retrying the same private
# QueryOrders/TradesHistory round-trip on every 10-second worker cycle.
_HISTORICAL_PROOF_TTL_S = 1800.0
_HISTORICAL_RECHECK_S = 600.0
_HISTORICAL_ORDER_RECHECK_AT: dict[str, float] = {}
_RECENT_DISCOVERY_RECHECK_AT = 0.0
_RECENT_DISCOVERY_INTERVAL_S = 60.0
_RECENT_DISCOVERY_LIMIT = 10


def _f(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _marker_ready() -> bool:
    try:
        probe = getattr(
            importlib.import_module("bot.runtime_kraken_margin_protection_truth_v367_patch"),
            "_execution_marker_ready", None,
        )
        if callable(probe):
            ready, _detail = probe()
            return bool(ready)
    except Exception:
        pass
    return False


def _candidate_order_ids() -> list[str]:
    """Inspect all known pending IDs, newest first, without inventing orders."""
    try:
        v363 = importlib.import_module("bot.runtime_kraken_deferred_fill_proof_recovery_v363_patch")
        loader = getattr(v363, "_load_pending", None)
        pending = dict(loader() or {}) if callable(loader) else {}
        ordered = sorted(
            pending.items(),
            key=lambda item: _f(dict(item[1] or {}).get("last_seen_epoch")
                                or dict(item[1] or {}).get("first_seen_epoch")),
            reverse=True,
        )
        ids = [str(oid).strip() for oid, _ in ordered
               if str(oid or "").strip() and not _historical_order_backoff_active(str(oid).strip())]
        if pending:
            return ids
    except Exception:
        LOGGER.exception("KNOWN_EXECUTION_PROBE_V406_PENDING_DISCOVERY_FAILED fail_closed=true")
        return []
    LOGGER.info("KNOWN_EXECUTION_PROBE_V406_NO_PENDING historical_fallback_only=true fresh_execution_not_proven=true trading_fail_closed=true")
    return [] if _historical_order_backoff_active(_FALLBACK_ORDER_ID) else [_FALLBACK_ORDER_ID]


def _candidate_order_id() -> str:
    """Compatibility wrapper; recovery itself inspects every candidate."""
    return next(iter(_candidate_order_ids()), "")


def _candidate_brokers() -> list[Any]:
    """Connected Kraken brokers from both canonical registries, deduplicated."""
    found: list[Any] = []
    seen: set[int] = set()

    try:
        v363 = importlib.import_module("bot.runtime_kraken_deferred_fill_proof_recovery_v363_patch")
        fn = getattr(v363, "_kraken_brokers", None)
        for broker in list(fn() or []) if callable(fn) else []:
            if broker is not None and id(broker) not in seen:
                seen.add(id(broker)); found.append(broker)
    except Exception:
        LOGGER.debug("v406c v363 broker discovery deferred", exc_info=True)

    try:
        v367 = importlib.import_module("bot.runtime_kraken_margin_protection_truth_v367_patch")
        fn = getattr(v367, "_account_brokers", None)
        for _account, broker in list(fn() or []) if callable(fn) else []:
            if broker is not None and id(broker) not in seen:
                seen.add(id(broker)); found.append(broker)
    except Exception:
        LOGGER.debug("v406c v367 broker discovery deferred", exc_info=True)

    return found


def _platform_broker(broker: Any) -> bool:
    """Require unambiguous canonical platform ownership, never user evidence."""
    try:
        v357 = importlib.import_module("bot.runtime_kraken_delayed_fill_reconciliation_v357_patch")
        scope = v357._recovery_scope(broker)
        return isinstance(scope, Mapping) and all(
            scope.get(key) == value for key, value in (
                ("broker", "kraken"), ("account", "platform:kraken"),
                ("account_id", "platform:kraken"),
            )
        )
    except Exception:
        return False


def _recent_candidate_order_ids() -> list[str]:
    """Discover candidates through bounded authenticated reads, never fill proof.

    Search by *closure* time so an older order filled recently is discoverable.
    A single page (at most 50 rows) is inspected once per minute; at most ten
    candidates then require the existing exact QueryOrders/canonical verifier.
    No ClosedOrders payload or observation timestamp is promoted to evidence.
    """
    global _RECENT_DISCOVERY_RECHECK_AT
    with _LOCK:
        mono = time.monotonic()
        if mono < _RECENT_DISCOVERY_RECHECK_AT:
            return []
        _RECENT_DISCOVERY_RECHECK_AT = mono + _RECENT_DISCOVERY_INTERVAL_S
    try:
        brokers = [broker for broker in _candidate_brokers() if _platform_broker(broker)]
        if len(brokers) != 1:
            LOGGER.info("KNOWN_EXECUTION_PROBE_V406_RECENT_UNAVAILABLE "
                        "reason=platform_scope_missing_or_ambiguous trading_fail_closed=true")
            return []
        v357 = importlib.import_module("bot.runtime_kraken_delayed_fill_reconciliation_v357_patch")
        now = time.time()
        if not math.isfinite(now) or now <= _HISTORICAL_PROOF_TTL_S:
            return []
        payload = v357._private_read(brokers[0], "ClosedOrders", {
            "start": math.floor(now - _HISTORICAL_PROOF_TTL_S) - 1,
            "end": math.ceil(now), "closetime": "close", "trades": False,
            "without_count": True,
        })
        if not isinstance(payload, Mapping) or payload.get("error") != []:
            LOGGER.info("KNOWN_EXECUTION_PROBE_V406_RECENT_UNAVAILABLE "
                        "reason=authenticated_read_unproven trading_fail_closed=true")
            return []
        result = payload.get("result")
        closed = result.get("closed") if isinstance(result, Mapping) else None
        if not isinstance(closed, Mapping) or len(closed) > 50:
            return []
        candidates = []
        for order_id, row in closed.items():
            if (not isinstance(order_id, str) or not order_id.strip()
                    or order_id != order_id.strip() or "," in order_id
                    or not isinstance(row, Mapping)):
                continue
            age = now - _f(row.get("closetm"))
            descr = row.get("descr")
            if (str(row.get("status") or "").lower() != "closed"
                    or not 0.0 <= age <= _HISTORICAL_PROOF_TTL_S
                    or _f(row.get("vol_exec")) <= 0.0 or _f(row.get("cost")) <= 0.0
                    or not isinstance(descr, Mapping) or not str(descr.get("pair") or "").strip()
                    or descr.get("type") not in {"buy", "sell"}
                    or _historical_order_backoff_active(order_id)):
                continue
            candidates.append((_f(row.get("closetm")), order_id))
        candidates.sort(reverse=True)
        LOGGER.info("KNOWN_EXECUTION_PROBE_V406_RECENT_CANDIDATES count=%d "
                    "scan_rows=%d scan_truncated_possible=%s max_age_s=1800 "
                    "exact_queryorders_still_required=true trading_authority_unchanged=true",
                    min(len(candidates), _RECENT_DISCOVERY_LIMIT), len(closed),
                    str(len(closed) == 50).lower())
        return [order_id for _, order_id in candidates[:_RECENT_DISCOVERY_LIMIT]]
    except Exception as exc:
        LOGGER.warning("KNOWN_EXECUTION_PROBE_V406_RECENT_UNAVAILABLE "
                       "reason=%s trading_fail_closed=true", type(exc).__name__)
        return []


def _final_authenticated_row(order_id: str) -> tuple[Any | None, Mapping[str, Any] | None]:
    """Return broker + exact authenticated final QueryOrders row, or no proof."""
    try:
        v357 = importlib.import_module("bot.runtime_kraken_delayed_fill_reconciliation_v357_patch")
        query = getattr(v357, "_query_order_row", None)
        brokers = _candidate_brokers()
        if not callable(query) or not brokers:
            return None, None
        for broker in brokers:
            if not _platform_broker(broker):
                continue
            try:
                row = query(broker, order_id)
            except Exception:
                continue
            if not isinstance(row, Mapping) or not row:
                continue
            status = str(row.get("status") or "").strip().lower()
            if status not in {"closed", "filled", "complete", "completed", "executed"}:
                continue
            if _f(row.get("vol_exec")) <= 0.0 or _f(row.get("cost")) <= 0.0:
                continue
            return broker, dict(row)
    except Exception:
        LOGGER.debug("v406c authenticated QueryOrders probe deferred", exc_info=True)
    return None, None


def _promote_same_authenticated_row(order_id: str, broker: Any, row: Mapping[str, Any]) -> tuple[bool, int]:
    """Reuse v357's exact authenticated reconciliation so event time remains authoritative."""
    v357 = importlib.import_module("bot.runtime_kraken_delayed_fill_reconciliation_v357_patch")
    v363 = importlib.import_module("bot.runtime_kraken_deferred_fill_proof_recovery_v363_patch")
    enrich = getattr(v357, "_enrich_kraken_final_order", None)
    promote = getattr(v363, "_promote_confirmed_fill", None)
    discard = getattr(v363, "_discard_pending", None)
    wake = getattr(v363, "_wake_activation", None)
    if not callable(enrich) or not callable(promote):
        return False, 0

    descr = row.get("descr") if isinstance(row.get("descr"), Mapping) else {}
    symbol = str(descr.get("pair") or "").strip().upper()
    side = str(descr.get("type") or "").strip().lower()
    if side not in {"buy", "sell"} or not symbol:
        return False, 0

    probe = {"order_id": order_id, "status": str(row.get("status") or "").strip().lower()}
    enriched = enrich(broker, probe, symbol=symbol, side=side)
    if not isinstance(enriched, Mapping):
        return False, 0
    # The second exact lookup may fail or expose different evidence. Never use
    # a final-status probe or a fresh first read to bless an unproven requery.
    if (str(enriched.get("order_id") or "").strip() != order_id
            or not any(enriched.get(key) is True for key in (
                "kraken_query_order_reconciled", "kraken_trade_history_reconciled"))
            or not _platform_broker(broker)
            or not 0.0 <= time.time() - _f(enriched.get("broker_fill_at_epoch")) <= _HISTORICAL_PROOF_TTL_S):
        return False, 0

    promoted = bool(promote(enriched, symbol=symbol, side=side))
    if not promoted:
        return False, 0

    if callable(discard):
        try:
            discard(order_id, "canonical_execution_proof_written_from_dynamic_authenticated_row")
        except Exception:
            LOGGER.debug("v406 dynamic pending cleanup deferred", exc_info=True)
    if callable(wake):
        try:
            wake()
        except Exception:
            LOGGER.debug("v406 dynamic activation wake deferred", exc_info=True)
    return True, 1


def _historical_order_backoff_active(order_id: str) -> bool:
    """Skip repeated reads for a known old final order; never skip new IDs."""
    now = time.monotonic()
    with _LOCK:
        for ident, deadline in tuple(_HISTORICAL_ORDER_RECHECK_AT.items()):
            if now >= deadline:
                _HISTORICAL_ORDER_RECHECK_AT.pop(ident, None)
        return now < _HISTORICAL_ORDER_RECHECK_AT.get(order_id, 0.0)


def _historical_final_order_age_s(row: Mapping[str, Any]) -> float:
    """Use only an authenticated FINAL QueryOrders closure time, never seen time.

    The caller rejects missing closure time before invoking this helper; never
    guess a timestamp or cache an unverified age as a historical outcome.
    """
    close_epoch = _f(row.get("closetm"))
    if close_epoch <= 0.0:
        return 0.0
    return time.time() - close_epoch


def recover_once() -> bool:
    if _marker_ready():
        return True
    candidates = list(dict.fromkeys(_recent_candidate_order_ids() + _candidate_order_ids()))
    if not candidates:
        LOGGER.info("KNOWN_EXECUTION_PROBE_V406_NO_ELIGIBLE_CANDIDATES pending_candidate_count=0 trading_fail_closed=true")
        return False
    LOGGER.info("KNOWN_EXECUTION_PROBE_V406_CANDIDATES count=%d read_only=true", len(candidates))
    for order_id in candidates:
        if _recover_candidate(order_id):
            return True
    return False


def _recover_candidate(order_id: str) -> bool:
    """Authenticate and reconcile one candidate; never authorize on lookup alone."""
    if not order_id or _historical_order_backoff_active(order_id):
    candidates = _candidate_order_ids()
    if not candidates:
        LOGGER.info("KNOWN_EXECUTION_PROBE_V406_NO_ELIGIBLE_CANDIDATES pending_candidate_count=0 trading_fail_closed=true")
        return False
    LOGGER.info("KNOWN_EXECUTION_PROBE_V406_CANDIDATES count=%d read_only=true", len(candidates))
    for order_id in candidates:
        if _recover_candidate(order_id):
            return True
    return False


def _recover_candidate(order_id: str) -> bool:
    """Authenticate and reconcile one candidate; never authorize on lookup alone."""
    broker, row = _final_authenticated_row(order_id)
    if row is None or broker is None:
        LOGGER.info(
            "KNOWN_EXECUTION_PROBE_V406_DEFERRED marker=%s order_id=%s reason=exact_authenticated_final_queryorders_row_unavailable dynamic_pending_order=true authoritative_v367_registry_enabled=true trading_fail_closed=true execution_proof_fabricated=false orders_submitted=false safety_gates_bypassed=false",
            MARKER, order_id,
        )
        return False
    close_epoch = _f(row.get("closetm"))
    if close_epoch <= 0.0 or close_epoch > time.time():
    if close_epoch <= 0.0 or close_epoch > time.time() + 30.0:
        LOGGER.warning(
            "KNOWN_EXECUTION_PROBE_V406_INVALID_CLOSE_TIME order_id=%s "
            "reason=missing_or_future_authenticated_closetm trading_fail_closed=true",
            order_id,
        )
        return False
    historical_age = _historical_final_order_age_s(row)
    if historical_age > _HISTORICAL_PROOF_TTL_S:
        # QueryOrders proved the exact order CLOSED with positive executed
        # volume/cost in _final_authenticated_row. A September fill must not be
        # restamped as an October fill or consume continual recovery API calls.
        with _LOCK:
            _HISTORICAL_ORDER_RECHECK_AT[order_id] = time.monotonic() + _HISTORICAL_RECHECK_S
        LOGGER.info(
            "KNOWN_EXECUTION_PROBE_V406_HISTORICAL_DEFERRED marker=%s order_id=%s "
            "broker_close_age_s=%.1f recheck_after_s=%.1f "
            "source=authenticated_queryorders_closetm old_broker_event_not_execution_ready=true "
            "historical_ledger_unchanged=true proof_timestamp_unchanged=true "
            "new_order_ids_unaffected=true orders_submitted=false trading_fail_closed=true",
            MARKER, order_id, historical_age, _HISTORICAL_RECHECK_S,
        )
        return False
    try:
        promoted, promoted_count = _promote_same_authenticated_row(order_id, broker, row)
    except Exception:
        LOGGER.exception("KNOWN_EXECUTION_PROBE_V406_RECOVERY_ERROR marker=%s order_id=%s fail_closed=true", MARKER, order_id)
        return False
    ready = _marker_ready()
    LOGGER.critical(
        "KNOWN_EXECUTION_PROBE_V406_RESULT marker=%s order_id=%s authenticated_queryorders_final=true positive_vol_exec=true positive_cost=true dynamic_pending_order=true same_authenticated_row_reused=true authoritative_v367_registry_enabled=true canonical_recovery_promoted=%s marker_ready=%s remembered_fill_values=false orders_submitted=false orders_cancelled=false forced_activation=false execution_proof_fabricated=false safety_gates_bypassed=false",
        MARKER, order_id, promoted_count if promoted else 0, str(ready).lower(),
    )
    return bool(ready)


def _worker() -> None:
    while not _marker_ready():
        try:
            if recover_once():
                return
        except Exception:
            LOGGER.exception("KNOWN_EXECUTION_PROBE_V406_WORKER_RETRY marker=%s", MARKER)
        time.sleep(10.0)


def install() -> bool:
    global _THREAD
    with _LOCK:
        os.environ[_READY_FLAG] = "1"
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(target=_worker, name="KnownExecutionProbeRevalidationV406", daemon=True)
            _THREAD.start()
        LOGGER.critical(
            "KNOWN_EXECUTION_PROBE_V406_READY marker=%s candidate_only=true dynamic_pending_order=true authoritative_v367_registry_enabled=true v363_registry_preserved=true broker_dedup=true exact_authenticated_queryorders_required=true final_status_required=true positive_vol_exec_required=true positive_cost_required=true same_authenticated_row_reused=true canonical_v357_v328_v346_authority_preserved=true remembered_fill_values=false orders_submitted=false orders_cancelled=false forced_activation=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


__all__ = ["install", "recover_once"]
