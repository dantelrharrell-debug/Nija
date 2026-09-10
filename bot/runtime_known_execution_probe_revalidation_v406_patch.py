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
_ORDER_ID = "OSW7F3-YD2NX-SR3BZB"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None


def _f(value: Any) -> float:
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


def _final_authenticated_row() -> tuple[Any | None, Mapping[str, Any] | None]:
    """Return broker + exact authenticated final QueryOrders row, or no proof."""
    try:
        v357 = importlib.import_module("bot.runtime_kraken_delayed_fill_reconciliation_v357_patch")
        query = getattr(v357, "_query_order_row", None)
        brokers = _candidate_brokers()
        if not callable(query) or not brokers:
            return None, None
        for broker in brokers:
            try:
                row = query(broker, _ORDER_ID)
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


def _promote_same_authenticated_row(row: Mapping[str, Any]) -> tuple[bool, int]:
    v357 = importlib.import_module("bot.runtime_kraken_delayed_fill_reconciliation_v357_patch")
    v363 = importlib.import_module("bot.runtime_kraken_deferred_fill_proof_recovery_v363_patch")
    parse = getattr(v357, "_query_order_fill", None)
    promote = getattr(v363, "_promote_confirmed_fill", None)
    record = getattr(v363, "record_pending_order", None)
    discard = getattr(v363, "_discard_pending", None)
    wake = getattr(v363, "_wake_activation", None)
    if not callable(parse) or not callable(promote) or not callable(record):
        return False, 0

    status, fill_price, filled_qty, filled_usd = parse(dict(row))
    if status not in {"closed", "filled", "complete", "completed", "executed"}:
        return False, 0
    if fill_price <= 0.0 or filled_qty <= 0.0 or filled_usd <= 0.0:
        return False, 0

    descr = row.get("descr") if isinstance(row.get("descr"), Mapping) else {}
    symbol = str(descr.get("pair") or "").strip().upper()
    side = str(descr.get("type") or "").strip().lower()
    if side not in {"buy", "sell"} or not symbol:
        return False, 0

    if not bool(record(order_id=_ORDER_ID, symbol=symbol, side=side, status=status)):
        return False, 0

    enriched = {
        "order_id": _ORDER_ID,
        "status": status,
        "filled_price": fill_price,
        "filled_size": filled_qty,
        "filled_size_usd": filled_usd,
        "kraken_query_order_reconciled": True,
        "kraken_query_order_authenticated": True,
    }
    promoted = bool(promote(enriched, symbol=symbol, side=side))
    if not promoted:
        return False, 0

    if callable(discard):
        try:
            discard(_ORDER_ID, "canonical_execution_proof_written_from_same_authenticated_row")
        except Exception:
            LOGGER.debug("v406c pending cleanup deferred", exc_info=True)
    if callable(wake):
        try:
            wake()
        except Exception:
            LOGGER.debug("v406c activation wake deferred", exc_info=True)
    return True, 1


def recover_once() -> bool:
    if _marker_ready():
        return True
    _broker, row = _final_authenticated_row()
    if row is None:
        LOGGER.info(
            "KNOWN_EXECUTION_PROBE_V406_DEFERRED marker=%s order_id=%s reason=exact_authenticated_final_queryorders_row_unavailable authoritative_v367_registry_enabled=true trading_fail_closed=true execution_proof_fabricated=false orders_submitted=false safety_gates_bypassed=false",
            MARKER, _ORDER_ID,
        )
        return False
    try:
        promoted, promoted_count = _promote_same_authenticated_row(row)
    except Exception:
        LOGGER.exception("KNOWN_EXECUTION_PROBE_V406_RECOVERY_ERROR marker=%s order_id=%s fail_closed=true", MARKER, _ORDER_ID)
        return False
    ready = _marker_ready()
    LOGGER.critical(
        "KNOWN_EXECUTION_PROBE_V406_RESULT marker=%s order_id=%s authenticated_queryorders_final=true positive_vol_exec=true positive_cost=true same_authenticated_row_reused=true authoritative_v367_registry_enabled=true canonical_recovery_promoted=%s marker_ready=%s remembered_fill_values=false orders_submitted=false orders_cancelled=false forced_activation=false execution_proof_fabricated=false safety_gates_bypassed=false",
        MARKER, _ORDER_ID, promoted_count if promoted else 0, str(ready).lower(),
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
            "KNOWN_EXECUTION_PROBE_V406_READY marker=%s candidate_only=true authoritative_v367_registry_enabled=true v363_registry_preserved=true broker_dedup=true exact_authenticated_queryorders_required=true final_status_required=true positive_vol_exec_required=true positive_cost_required=true same_authenticated_row_reused=true canonical_v357_v328_v346_authority_preserved=true remembered_fill_values=false orders_submitted=false orders_cancelled=false forced_activation=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


__all__ = ["install", "recover_once"]
