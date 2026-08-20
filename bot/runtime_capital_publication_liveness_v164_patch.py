"""Converge canonical capital publication and coordinator-worker liveness.

Production after v163 proved LIVE_ACTIVE, position-sync proof, writer authority,
and three-venue connectivity, but exposed two remaining capital-path defects:

* capital_publication_convergence_v43 only searched legacy broker_manager
  registries when deciding whether a fresh omitted broker observation belonged
  to a connected platform broker. The live canonical registry is the
  MultiAccountBrokerManager, so Kraken could be execution-ready yet omitted from
  a 2/3 publication;
* v142 correctly generation-fenced timed-out coordinator workers, but repeated
  rollover could accumulate retired daemon coordinator generations if old
  workers were slow to unwind.

v164 repairs both paths without extending freshness, inventing balances, or
weakening any execution gate:

* teach v43 to resolve connected platform brokers from the canonical MABM;
* run v43 augmentation before publication and reject a partial authorized
  snapshot when a complete, positive, still-current CapitalAuthority snapshot
  already exists. The existing complete snapshot remains authoritative until a
  complete replacement or normal expiry;
* cap concurrently alive v142 runtime-refresh worker generations. When the cap
  is reached, rollover is deferred and the timed-out coordinator remains
  fail-closed until its daemon unwinds instead of spawning an unbounded backlog.

No stale timestamp is refreshed, no partial snapshot is promoted to complete,
no kill switch is cleared, and no LIVE/order/risk gate is bypassed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_publication_liveness_v164")
MARKER = "20260819-runtime-capital-publication-liveness-v164"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_PUBLICATION_LIVENESS_V164_READY"
_PATCH_ATTR = "_nija_runtime_capital_publication_liveness_v164"
_LOCK = threading.RLock()


def _normalize_broker_name(value: Any) -> str:
    text = str(getattr(value, "value", value) or "").strip().lower()
    for broker_id in ("kraken", "coinbase", "okx", "alpaca"):
        if broker_id in text:
            return broker_id
    return text


def _canonical_manager() -> Any:
    try:
        module = importlib.import_module("bot.multi_account_broker_manager")
        getter = getattr(module, "get_broker_manager", None)
        if callable(getter):
            return getter()
        return getattr(module, "_manager", None) or getattr(
            module, "multi_account_broker_manager", None
        )
    except Exception:
        return None


def _manager_platform_mapping(manager: Any) -> dict[Any, Any]:
    if manager is None:
        return {}
    for attr in ("platform_brokers", "_platform_brokers"):
        value = getattr(manager, attr, None)
        if callable(value):
            try:
                value = value()
            except Exception:
                value = None
        if isinstance(value, dict):
            return dict(value)
    return {}


def _manager_connected(manager: Any, key: Any, broker: Any) -> bool:
    if broker is None:
        return False
    if bool(getattr(broker, "connected", False)):
        return True
    probe = getattr(manager, "is_platform_connected", None)
    if callable(probe):
        try:
            if bool(probe(key)):
                return True
        except Exception:
            pass
    state_map = getattr(manager, "_platform_state", None)
    if isinstance(state_map, dict):
        state = state_map.get(key)
        if state is None:
            state = state_map.get(_normalize_broker_name(key))
        state_value = str(getattr(state, "value", state) or "").strip().lower()
        if state_value == "connected":
            return True
    return False


def _canonical_platform_instance(broker_id: str) -> Any:
    """Return a connected platform broker from the canonical MABM, if proven."""
    target = _normalize_broker_name(broker_id)
    manager = _canonical_manager()
    for key, broker in _manager_platform_mapping(manager).items():
        name = _normalize_broker_name(key)
        if name != target:
            name = _normalize_broker_name(
                getattr(broker, "broker_type", None)
                or getattr(broker, "broker_name", None)
                or getattr(broker, "name", None)
                or broker.__class__.__name__
            )
        if name == target and _manager_connected(manager, key, broker):
            return broker
    return None


def _patch_v43_connectivity() -> bool:
    try:
        v43 = importlib.import_module("bot.capital_publication_convergence_v43_patch")
    except Exception as exc:
        LOGGER.error(
            "CAPITAL_V164_V43_IMPORT_FAILED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False
    current = getattr(v43, "_connected_platform_instance", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def connected_v164(broker_id: str) -> Any:
        try:
            instance = original(broker_id)
        except Exception:
            instance = None
        if instance is not None:
            return instance
        instance = _canonical_platform_instance(broker_id)
        if instance is not None:
            LOGGER.info(
                "CAPITAL_V164_CANONICAL_CONNECTIVITY_USED marker=%s broker=%s source=mabm",
                MARKER,
                _normalize_broker_name(broker_id),
            )
        return instance

    setattr(connected_v164, _PATCH_ATTR, True)
    setattr(connected_v164, "__wrapped__", original)
    v43._connected_platform_instance = connected_v164
    return True


def _snapshot_complete_positive(snapshot: Any) -> bool:
    if snapshot is None:
        return False
    try:
        expected = max(1, int(getattr(snapshot, "expected_brokers", 0) or 0))
        count = max(0, int(getattr(snapshot, "broker_count", 0) or 0))
        real = float(getattr(snapshot, "real_capital", 0.0) or 0.0)
    except (TypeError, ValueError, OverflowError):
        return False
    balances = getattr(snapshot, "broker_balances", None)
    positive = 0
    if isinstance(balances, dict):
        for value in balances.values():
            try:
                if float(value) > 0.0:
                    positive += 1
            except (TypeError, ValueError, OverflowError):
                continue
    return bool(real > 0.0 and count >= expected and positive >= expected)


def _snapshot_partial(snapshot: Any) -> bool:
    if snapshot is None:
        return False
    try:
        expected = max(1, int(getattr(snapshot, "expected_brokers", 0) or 0))
        count = max(0, int(getattr(snapshot, "broker_count", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        return True
    return count < expected


def _current_complete_fresh(authority: Any) -> Any:
    status_getter = getattr(authority, "get_snapshot_publication_status", None)
    if not callable(status_getter):
        return None
    try:
        status = status_getter()
    except Exception:
        return None
    if not bool(getattr(status, "accepted", False)) or bool(getattr(status, "stale", True)):
        return None
    getter = getattr(authority, "get_typed_snapshot", None)
    current = None
    if callable(getter):
        try:
            current = getter()
        except Exception:
            current = None
    if current is None:
        current = getattr(authority, "_last_typed_snapshot", None)
    return current if _snapshot_complete_positive(current) else None


def _augment_candidate(snapshot: Any) -> Any:
    try:
        v43 = importlib.import_module("bot.capital_publication_convergence_v43_patch")
        augment = getattr(v43, "_augment_snapshot", None)
        if callable(augment):
            repaired, _additions = augment(snapshot)
            return repaired
    except Exception as exc:
        LOGGER.debug(
            "CAPITAL_V164_AUGMENT_PROBE_FAILED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
    return snapshot


def _patch_partial_publication_guard() -> bool:
    try:
        ca = importlib.import_module("bot.capital_authority")
    except Exception:
        return False
    cls = getattr(ca, "CapitalAuthority", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "publish_snapshot", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def publish_v164(self: Any, snapshot: Any, writer_id: str) -> bool:
        authorized = str(getattr(self, "_AUTHORIZED_WRITER_ID", "") or "")
        candidate = snapshot
        if str(writer_id or "") == authorized:
            candidate = _augment_candidate(snapshot)
            if _snapshot_partial(candidate):
                previous = _current_complete_fresh(self)
                if previous is not None:
                    LOGGER.warning(
                        "CAPITAL_V164_PARTIAL_DOWNGRADE_REJECTED marker=%s incoming=%s/%s incoming_real=%.2f "
                        "current=%s/%s current_real=%.2f publication_status_unchanged=true refresh_required=true",
                        MARKER,
                        getattr(candidate, "broker_count", "?"),
                        getattr(candidate, "expected_brokers", "?"),
                        float(getattr(candidate, "real_capital", 0.0) or 0.0),
                        getattr(previous, "broker_count", "?"),
                        getattr(previous, "expected_brokers", "?"),
                        float(getattr(previous, "real_capital", 0.0) or 0.0),
                    )
                    return False
        return bool(original(self, candidate, writer_id=writer_id))

    setattr(publish_v164, _PATCH_ATTR, True)
    setattr(publish_v164, "__wrapped__", original)
    cls.publish_snapshot = publish_v164
    return True


def _max_runtime_refresh_threads() -> int:
    raw = str(os.environ.get("NIJA_CAPITAL_MAX_RUNTIME_REFRESH_THREADS", "2") or "2").strip()
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        value = 2
    return max(1, min(value, 4))


def _runtime_refresh_threads() -> list[threading.Thread]:
    return [
        thread
        for thread in threading.enumerate()
        if bool(getattr(thread, "is_alive", lambda: False)())
        and str(getattr(thread, "name", "")).startswith("capital-runtime-refresh-v142-g")
    ]


def _rollover_thread_cap_reached() -> tuple[bool, int, int]:
    live = len(_runtime_refresh_threads())
    maximum = _max_runtime_refresh_threads()
    return live >= maximum, live, maximum


def _patch_v142_rollover_containment() -> bool:
    try:
        v142 = importlib.import_module("bot.capital_publication_liveness_v142_patch")
    except Exception:
        return False
    current = getattr(v142, "_rollover_coordinator", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def rollover_v164(
        manager: Any,
        *,
        expected_old: Any = None,
        reason: str,
    ) -> Any:
        old = getattr(manager, "_capital_coordinator", None)
        if old is not None and (expected_old is None or old is expected_old):
            capped, live, maximum = _rollover_thread_cap_reached()
            thread = getattr(old, "_nija_v142_flight_thread", None)
            old_alive = bool(
                thread is not None
                and callable(getattr(thread, "is_alive", None))
                and thread.is_alive()
            )
            if capped and old_alive:
                LOGGER.critical(
                    "CAPITAL_V164_ROLLOVER_DEFERRED marker=%s reason=%s live_runtime_refresh_threads=%d "
                    "max_runtime_refresh_threads=%d current_coordinator_preserved=true generation_fence_preserved=true "
                    "new_worker_started=false trading_fail_closed_until_unwind=true",
                    MARKER,
                    reason,
                    live,
                    maximum,
                )
                return old
        return original(manager, expected_old=expected_old, reason=reason)

    setattr(rollover_v164, _PATCH_ATTR, True)
    setattr(rollover_v164, "__wrapped__", original)
    v142._rollover_coordinator = rollover_v164
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_publication_liveness_v164"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        v43_ok = _patch_v43_connectivity()
        publish_ok = _patch_partial_publication_guard()
        rollover_ok = _patch_v142_rollover_containment()
        manifest_ok = _patch_release_manifest()
        ready = bool(v43_ok and publish_ok and rollover_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_CAPITAL_PUBLICATION_LIVENESS_V164_FAILED marker=%s v43_ok=%s publish_ok=%s "
                "rollover_ok=%s manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(v43_ok).lower(),
                str(publish_ok).lower(),
                str(rollover_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        capped, live, maximum = _rollover_thread_cap_reached()
        LOGGER.critical(
            "RUNTIME_CAPITAL_PUBLICATION_LIVENESS_V164 marker=%s ready=true mabm_connectivity_for_v43=true "
            "partial_downgrade_guard=true runtime_refresh_thread_cap=%d current_runtime_refresh_threads=%d "
            "cap_currently_reached=%s freshness_extended=false stale_promoted=false safety_gates_bypassed=false",
            MARKER,
            maximum,
            live,
            str(capped).lower(),
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_canonical_platform_instance",
    "_snapshot_complete_positive",
    "_snapshot_partial",
    "_current_complete_fresh",
    "_max_runtime_refresh_threads",
    "_runtime_refresh_threads",
    "_rollover_thread_cap_reached",
]
