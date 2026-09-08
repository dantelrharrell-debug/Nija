"""Authenticated recovery of NIJA's previously verified Kraken execution probe.

This patch is a liveness fallback only.  A known historical order id is treated
as a *candidate*, never as proof.  Before it is queued into the existing v363
recovery path, the current connected Kraken broker must return the exact
QueryOrders row with a final state, positive executed volume, and positive cost.
The existing v357 -> v328 -> v346 chain remains the sole fill/proof authority.

No price/notional/fill value is remembered here.  No order is submitted,
cancelled, resized, or modified.  No writer/nonce/risk/capital/position/kill
switch/activation/protective-exit gate is changed or bypassed.
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
MARKER = "20260908-runtime-known-execution-probe-revalidation-v406"
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
            "_execution_marker_ready",
            None,
        )
        if callable(probe):
            ready, _detail = probe()
            return bool(ready)
    except Exception:
        pass
    return False


def _final_authenticated_row() -> tuple[Any | None, Mapping[str, Any] | None]:
    """Return broker + exact authenticated final QueryOrders row, or no proof."""
    try:
        v363 = importlib.import_module("bot.runtime_kraken_deferred_fill_proof_recovery_v363_patch")
        v357 = importlib.import_module("bot.runtime_kraken_delayed_fill_reconciliation_v357_patch")
        brokers_fn = getattr(v363, "_kraken_brokers", None)
        query = getattr(v357, "_query_order_row", None)
        brokers = list(brokers_fn() or []) if callable(brokers_fn) else []
        if not callable(query):
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
            return broker, row
    except Exception:
        LOGGER.debug("v406 authenticated QueryOrders probe deferred", exc_info=True)
    return None, None


def recover_once() -> bool:
    if _marker_ready():
        return True

    broker, row = _final_authenticated_row()
    if broker is None or row is None:
        LOGGER.info(
            "KNOWN_EXECUTION_PROBE_V406_DEFERRED marker=%s order_id=%s "
            "reason=exact_authenticated_final_queryorders_row_unavailable "
            "trading_fail_closed=true execution_proof_fabricated=false orders_submitted=false "
            "safety_gates_bypassed=false",
            MARKER, _ORDER_ID,
        )
        return False

    descr = row.get("descr") if isinstance(row.get("descr"), Mapping) else {}
    symbol = str(descr.get("pair") or "").strip().upper()
    side = str(descr.get("type") or "").strip().lower()
    try:
        v363 = importlib.import_module("bot.runtime_kraken_deferred_fill_proof_recovery_v363_patch")
        record = getattr(v363, "record_pending_order", None)
        recover = getattr(v363, "recover_once", None)
        if not callable(record) or not callable(recover):
            return False
        if not bool(record(order_id=_ORDER_ID, symbol=symbol, side=side, status=str(row.get("status") or ""))):
            return False
        promoted = int(recover() or 0)
    except Exception:
        LOGGER.exception(
            "KNOWN_EXECUTION_PROBE_V406_RECOVERY_ERROR marker=%s order_id=%s fail_closed=true",
            MARKER, _ORDER_ID,
        )
        return False

    ready = _marker_ready()
    LOGGER.critical(
        "KNOWN_EXECUTION_PROBE_V406_RESULT marker=%s order_id=%s "
        "authenticated_queryorders_final=true positive_vol_exec=true positive_cost=true "
        "canonical_recovery_promoted=%s marker_ready=%s remembered_fill_values=false "
        "orders_submitted=false orders_cancelled=false forced_activation=false "
        "execution_proof_fabricated=false safety_gates_bypassed=false",
        MARKER, _ORDER_ID, promoted, str(ready).lower(),
    )
    return ready


def _worker() -> None:
    while not _marker_ready():
        try:
            if recover_once():
                return
        except Exception:
            LOGGER.exception("KNOWN_EXECUTION_PROBE_V406_WORKER_RETRY marker=%s", MARKER)
        time.sleep(20.0)


def install() -> bool:
    global _THREAD
    with _LOCK:
        os.environ[_READY_FLAG] = "1"
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(
                target=_worker,
                name="KnownExecutionProbeRevalidationV406",
                daemon=True,
            )
            _THREAD.start()
        LOGGER.critical(
            "KNOWN_EXECUTION_PROBE_V406_READY marker=%s candidate_only=true "
            "exact_authenticated_queryorders_required=true final_status_required=true "
            "positive_vol_exec_required=true positive_cost_required=true "
            "canonical_v357_v328_v346_authority_preserved=true remembered_fill_values=false "
            "orders_submitted=false orders_cancelled=false forced_activation=false "
            "safety_gates_bypassed=false",
            MARKER,
        )
        return True


__all__ = ["install", "recover_once"]
