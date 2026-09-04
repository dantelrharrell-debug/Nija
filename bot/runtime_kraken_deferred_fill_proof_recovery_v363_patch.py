"""Deferred Kraken confirmed-fill proof recovery v363.

Production on 2026-09-04 showed real Kraken order/position activity while the
canonical proof layer never promoted a qualifying authenticated fill into the
v346 execution marker, so ``execution_ready`` stayed false and activation stayed
off for new entries.

The chain itself is correct:

``v357`` (delayed Kraken reconciliation) -> ``v328._normalize_dict_fill``
(canonical confirmed-fill verifier) -> ``v346`` (canonical execution marker) ->
``v169``/``v231`` (execution provenance + ``execution_ready``).

The gap is liveness, not policy.  v357 reconciles **once**, synchronously, right
after submission.  A Kraken order that is only acknowledged at that moment (real
txid, non-final status, no ``vol_exec``/``cost``) makes ``v328`` raise
``ACK timeout pending reconciliation`` and the order id is then discarded.  When
Kraken later exposes the authenticated fill through ``QueryOrders`` /
``TradesHistory`` nothing re-drives the reconciliation, so the canonical marker
is never written even though genuine fill evidence exists.

v363 closes only that gap:

1. Every Kraken submission that yields a real exchange order id but no
   fill-specific evidence is recorded in a durable pending-proof registry
   (survives process restarts, so a fill that settles after a redeploy is still
   recoverable).
2. A background worker re-drives the **existing** read-only v357 reconciliation
   for those exact order ids against a connected Kraken broker.
3. Only when v357 admits real fill evidence (exact ``QueryOrders`` row in a final
   state with positive ``vol_exec``/``cost``, or ``TradesHistory`` rows whose
   ``ordertxid`` exactly equals the order id) is the enriched result handed to
   the canonical ``v328`` verifier, which is what makes ``v346`` write the
   canonical execution marker.

No ACK, remembered position, requested notional, price hint, market price,
unrelated trade row, or broker connectivity is promoted to fill proof.  This
patch issues no order mutation and does not change writer/nonce/risk/capital/
position-sync/ECEL/broker-health/minimum-order/kill-switch/rejection or
protective-exit policy.  If no authenticated evidence exists, NIJA stays fail
closed rather than fabricating readiness.
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import threading
import time
from collections.abc import Mapping
from functools import wraps
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_deferred_fill_proof_recovery_v363")
MARKER = "20260904-runtime-kraken-deferred-fill-proof-recovery-v363"
RELEASE_ID = "20260904-runtime-convergence-v363"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_DEFERRED_FILL_PROOF_RECOVERY_V363_READY"
_PATCH_ATTR = "_nija_kraken_deferred_fill_proof_recovery_v363"

_LOCK = threading.RLock()
_STATE_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None

_DEFAULT_STATE_PATH = "./data/kraken_pending_fill_proof.json"
_DEFAULT_INTERVAL_S = 20.0
_DEFAULT_MAX_AGE_S = 7 * 24 * 3600.0
_MAX_PENDING = 64


def _state_path() -> Path:
    return Path(
        os.environ.get("NIJA_KRAKEN_PENDING_FILL_PROOF_PATH", _DEFAULT_STATE_PATH)
    )


def _interval_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_FILL_PROOF_RECOVERY_INTERVAL_S", "") or _DEFAULT_INTERVAL_S)
    except (TypeError, ValueError):
        return _DEFAULT_INTERVAL_S
    return max(5.0, value)


def _max_age_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_FILL_PROOF_MAX_AGE_S", "") or _DEFAULT_MAX_AGE_S)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_AGE_S
    return max(60.0, value)


def _v357() -> Any:
    return importlib.import_module("bot.runtime_kraken_delayed_fill_reconciliation_v357_patch")


def _v328() -> Any:
    return importlib.import_module("bot.runtime_confirmed_fill_profitability_v328_patch")


def _load_pending() -> dict[str, dict[str, Any]]:
    path = _state_path()
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except Exception:
        return {}
    if not raw.startswith("{"):
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    orders = payload.get("orders") if isinstance(payload, Mapping) else None
    if not isinstance(orders, Mapping):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for order_id, entry in orders.items():
        oid = str(order_id or "").strip()
        if oid and isinstance(entry, Mapping):
            out[oid] = dict(entry)
    return out


def _store_pending(orders: Mapping[str, Mapping[str, Any]]) -> None:
    path = _state_path()
    payload = {
        "version": 1,
        "marker": MARKER,
        "updated_at_epoch": time.time(),
        "orders": {str(k): dict(v) for k, v in orders.items()},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:
        LOGGER.warning(
            "KRAKEN_FILL_PROOF_V363_STATE_WRITE_FAILED marker=%s error=%s:%s fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )


def record_pending_order(
    *,
    order_id: str,
    symbol: str = "",
    side: str = "",
    status: str = "",
) -> bool:
    """Remember a real Kraken order id whose fill evidence is not yet available."""
    oid = str(order_id or "").strip()
    if not oid:
        return False
    with _STATE_LOCK:
        pending = _load_pending()
        entry = dict(pending.get(oid) or {})
        now = time.time()
        entry.setdefault("first_seen_epoch", now)
        entry["last_seen_epoch"] = now
        entry["symbol"] = str(symbol or entry.get("symbol") or "").strip().upper()
        entry["side"] = str(side or entry.get("side") or "").strip().lower()
        entry["status"] = str(status or entry.get("status") or "").strip().lower()
        pending[oid] = entry
        if len(pending) > _MAX_PENDING:
            ordered = sorted(
                pending.items(),
                key=lambda item: float(item[1].get("first_seen_epoch") or 0.0),
                reverse=True,
            )
            pending = dict(ordered[:_MAX_PENDING])
        _store_pending(pending)
    LOGGER.info(
        "KRAKEN_FILL_PROOF_V363_PENDING_RECORDED marker=%s order_id=%s symbol=%s side=%s status=%s "
        "ack_not_fill=true deferred_authenticated_reconciliation=true execution_proof_fabricated=false",
        MARKER, oid, entry.get("symbol") or "unknown", entry.get("side") or "unknown",
        entry.get("status") or "unknown",
    )
    return True


def _discard_pending(order_id: str, reason: str) -> None:
    oid = str(order_id or "").strip()
    if not oid:
        return
    with _STATE_LOCK:
        pending = _load_pending()
        if pending.pop(oid, None) is None:
            return
        _store_pending(pending)
    LOGGER.info(
        "KRAKEN_FILL_PROOF_V363_PENDING_CLEARED marker=%s order_id=%s reason=%s",
        MARKER, oid, reason,
    )


def _seed_orders() -> None:
    """Allow operators to re-queue known Kraken order ids for authenticated recovery.

    Seeding only schedules read-only ``QueryOrders``/``TradesHistory`` lookups.
    Proof still requires real exchange fill evidence for that exact order id.
    """
    raw = str(os.environ.get("NIJA_KRAKEN_RECOVER_FILL_ORDER_IDS", "") or "").strip()
    if not raw:
        return
    for token in raw.replace(";", ",").split(","):
        item = token.strip()
        if not item:
            continue
        parts = [part.strip() for part in item.split(":")]
        order_id = parts[0]
        symbol = parts[1] if len(parts) > 1 else ""
        side = parts[2] if len(parts) > 2 else ""
        if order_id:
            record_pending_order(order_id=order_id, symbol=symbol, side=side)


def _is_kraken_broker(broker: Any) -> bool:
    try:
        return bool(_v357()._is_kraken(broker))
    except Exception:
        return False


def _connected(broker: Any) -> bool:
    try:
        return bool(getattr(broker, "connected", False))
    except Exception:
        return False


def _kraken_brokers() -> list[Any]:
    """Return connected Kraken brokers from the canonical multi-account manager."""
    try:
        module = importlib.import_module("bot.multi_account_broker_manager")
        getter = getattr(module, "get_broker_manager", None)
        manager = getter() if callable(getter) else getattr(module, "multi_account_broker_manager", None)
    except Exception:
        manager = None
    if manager is None:
        return []

    found: list[Any] = []
    seen: set[int] = set()

    def _collect(mapping: Any) -> None:
        try:
            if callable(mapping):
                mapping = mapping()
            items = tuple(dict(mapping or {}).items())
        except Exception:
            return
        for _key, broker in items:
            if broker is None or id(broker) in seen:
                continue
            if not _is_kraken_broker(broker) or not _connected(broker):
                continue
            seen.add(id(broker))
            found.append(broker)

    _collect(getattr(manager, "platform_brokers", None))
    try:
        for _account, brokers in dict(getattr(manager, "user_brokers", {}) or {}).items():
            _collect(brokers)
    except Exception:
        pass
    return found


def _promote_confirmed_fill(enriched: Mapping[str, Any], *, symbol: str, side: str) -> bool:
    """Hand a reconciled Kraken result to the canonical v328/v346 proof layer."""
    try:
        normalize = getattr(_v328(), "_normalize_dict_fill", None)
        if not callable(normalize):
            return False
        price, filled_usd = normalize(dict(enriched), symbol=symbol, side=side)
    except Exception as exc:
        LOGGER.info(
            "KRAKEN_FILL_PROOF_V363_NOT_YET_PROVEN marker=%s symbol=%s side=%s reason=%s:%s fail_closed=true",
            MARKER, symbol or "unknown", side or "unknown", type(exc).__name__, exc,
        )
        return False
    LOGGER.critical(
        "KRAKEN_FILL_PROOF_V363_CANONICAL_PROOF_PROMOTED marker=%s order_id=%s symbol=%s side=%s "
        "fill_price=%.10f filled_usd=%.8f authenticated_kraken_fill=true exact_order_match=true "
        "read_only_recovery=true ack_not_fill=true position_appearance_not_proof=true "
        "requested_notional_promoted=false market_price_promoted=false execution_proof_fabricated=false "
        "safety_gates_bypassed=false",
        MARKER, str(enriched.get("order_id") or "").strip(), symbol or "unknown", side or "unknown",
        float(price), float(filled_usd),
    )
    return True


def _wake_activation() -> None:
    for module_name, attr, arg in (
        ("bot.runtime_execution_position_readiness_v346_patch", "_wake_activation_after_proof", None),
        ("bot.runtime_execution_position_readiness_v346_patch", "_wake_position_sync", None),
    ):
        try:
            fn = getattr(importlib.import_module(module_name), attr, None)
            if callable(fn):
                fn() if arg is None else fn(arg)
        except Exception:
            LOGGER.debug("v363 activation wake deferred", exc_info=True)


def _descr_field(row: Mapping[str, Any], key: str) -> str:
    descr = row.get("descr")
    if isinstance(descr, Mapping):
        return str(descr.get(key) or "").strip()
    return ""


def recover_once() -> int:
    """Re-drive authenticated Kraken fill reconciliation for pending order ids."""
    with _STATE_LOCK:
        pending = _load_pending()
    if not pending:
        return 0

    brokers = _kraken_brokers()
    if not brokers:
        LOGGER.debug("v363 recovery deferred: no connected Kraken broker")
        return 0

    v357 = _v357()
    enrich = getattr(v357, "_enrich_kraken_final_order", None)
    query_row = getattr(v357, "_query_order_row", None)
    if not callable(enrich):
        return 0

    max_age = _max_age_s()
    now = time.time()
    promoted = 0

    for order_id, entry in list(pending.items()):
        try:
            first_seen = float(entry.get("first_seen_epoch"))
        except (TypeError, ValueError):
            first_seen = now
        if now - first_seen > max_age:
            _discard_pending(order_id, "recovery_window_expired")
            continue

        symbol = str(entry.get("symbol") or "").strip().upper()
        side = str(entry.get("side") or "").strip().lower()

        for broker in brokers:
            if callable(query_row) and (not symbol or side not in {"buy", "sell"}):
                try:
                    row = query_row(broker, order_id)
                except Exception:
                    row = {}
                if isinstance(row, Mapping) and row:
                    symbol = symbol or _descr_field(row, "pair").upper()
                    if side not in {"buy", "sell"}:
                        candidate = _descr_field(row, "type").lower()
                        side = candidate if candidate in {"buy", "sell"} else side

            probe = {
                "order_id": order_id,
                "status": str(entry.get("status") or "").strip().lower(),
            }
            try:
                enriched = enrich(broker, probe, symbol=symbol, side=side)
            except Exception as exc:
                LOGGER.info(
                    "KRAKEN_FILL_PROOF_V363_RECONCILE_DEFERRED marker=%s order_id=%s error=%s:%s "
                    "fail_closed=true",
                    MARKER, order_id, type(exc).__name__, exc,
                )
                continue
            if not isinstance(enriched, Mapping):
                continue
            if not (
                enriched.get("kraken_query_order_reconciled")
                or enriched.get("kraken_trade_history_reconciled")
            ):
                continue
            if _promote_confirmed_fill(enriched, symbol=symbol, side=side):
                promoted += 1
                _discard_pending(order_id, "canonical_execution_proof_written")
                _wake_activation()
                break

    return promoted


def _patch_v357_enrichment() -> bool:
    """Record real-but-unproven Kraken order ids for deferred recovery."""
    module = _v357()
    current = getattr(module, "_enrich_kraken_final_order", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def enrich_v363(broker: Any, result: Any, *, symbol: str, side: str):
        enriched = current(broker, result, symbol=symbol, side=side)
        try:
            if not _is_kraken_broker(broker) or not isinstance(enriched, Mapping):
                return enriched
            order_id = str(module._order_id(enriched) or "").strip()
            if not order_id:
                return enriched
            if module._has_fill_specific(enriched):
                _discard_pending(order_id, "fill_specific_evidence_present")
                return enriched
            record_pending_order(
                order_id=order_id,
                symbol=symbol,
                side=side,
                status=str(enriched.get("status") or "").strip().lower(),
            )
        except Exception:
            LOGGER.debug("v363 pending capture deferred", exc_info=True)
        return enriched

    setattr(enrich_v363, _PATCH_ATTR, True)
    setattr(enrich_v363, "__wrapped__", current)
    module._enrich_kraken_final_order = enrich_v363
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_deferred_fill_proof_recovery_v363"] = _READY_FLAG
        return True
    except Exception:
        return False


def _worker() -> None:
    while True:
        try:
            _patch_v357_enrichment()
            recover_once()
        except Exception:
            LOGGER.debug("v363 worker pulse failed", exc_info=True)
        time.sleep(_interval_s())


def install_import_hook() -> bool:
    global _THREAD
    with _LOCK:
        patch_ok = manifest_ok = False
        try:
            patch_ok = _patch_v357_enrichment()
            manifest_ok = _register_manifest()
            _seed_orders()
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_KRAKEN_DEFERRED_FILL_PROOF_RECOVERY_V363_INSTALL_ERROR marker=%s error=%s:%s "
                "fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        ready = bool(patch_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready and (_THREAD is None or not _THREAD.is_alive()):
            _THREAD = threading.Thread(
                target=_worker, name="KrakenDeferredFillProofV363", daemon=True
            )
            _THREAD.start()
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_KRAKEN_DEFERRED_FILL_PROOF_RECOVERY_V363_%s marker=%s ready=%s "
            "durable_pending_registry=true deferred_authenticated_reconciliation=true "
            "queryorders_exact_order_required=true trade_history_ordertxid_exact_match=true "
            "canonical_v328_verifier_required=true canonical_v346_marker_owner=true "
            "ack_not_fill=true position_appearance_not_fill=true requested_notional_promoted=false "
            "market_price_promoted=false order_mutation=false "
            "writer_nonce_risk_capital_position_killswitch_ecel_broker_health_minimum_order_fill_gates_"
            "unchanged=true protective_exits_unchanged=true forced_trade=false forced_activation=false "
            "execution_proof_fabricated=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "record_pending_order", "recover_once",
]
