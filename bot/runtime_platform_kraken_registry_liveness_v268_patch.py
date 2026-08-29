"""Canonical platform Kraken registry liveness repair v268.

Production deployment 7a413766 showed a split platform-Kraken truth: startup
position sync used a connected PLATFORM Kraken instance while the canonical
MultiAccountBrokerManager later reported its Kraken platform entry disconnected.
That left platform connectivity at 2/3 and correctly blocked capital publication.

The underlying registry contract distinguishes two facts:

* GLOBAL_PLATFORM_BROKERS[key] means a process-wide platform broker instance
  exists; and
* _PLATFORM_BROKER_CONNECTED[key] means that instance completed its connection
  lifecycle.

MultiAccountBrokerManager.refresh_registry() historically collapsed those facts
by assigning GLOBAL_PLATFORM_BROKERS[key] = broker.connected.  A transient
connection false therefore removed the instance-presence guard and could allow a
second platform broker object to be created on a later initialization pass.

v268 repairs only that ownership/liveness split.  It preserves a broker-instance
presence guard whenever an object exists, keeps connectivity in the dedicated
connected registry, and can reconcile an already-split Kraken manager only when
there is exactly one live, actually-connected PLATFORM KrakenBroker candidate.
Ambiguous multiple connected platform instances remain fail closed.  No balance,
capital freshness, nonce, execution authority, kill-switch state, order/fill
proof, or broker connection is fabricated.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_platform_kraken_registry_liveness_v268")
MARKER = "20260828-platform-kraken-registry-liveness-v268"
RELEASE_ID = "20260828-runtime-convergence-v268"
_READY_FLAG = "NIJA_RUNTIME_PLATFORM_KRAKEN_REGISTRY_LIVENESS_V268_READY"
_PATCH_ATTR = "_nija_runtime_platform_kraken_registry_liveness_v268"
_LOCK = threading.RLock()


def _label(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _is_platform_account(broker: Any) -> bool:
    account = _label(getattr(broker, "account_type", ""))
    return account == "platform" or account.endswith(".platform")


def _actually_connected(broker: Any) -> bool:
    if broker is None:
        return False
    try:
        return bool(getattr(broker, "connected", False))
    except Exception:
        return False


def _canonical_manager() -> Any:
    module = sys.modules.get("bot.multi_account_broker_manager")
    if not isinstance(module, ModuleType):
        try:
            module = importlib.import_module("bot.multi_account_broker_manager")
        except Exception:
            return None
    getter = getattr(module, "get_broker_manager", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            pass
    return getattr(module, "_manager", None) or getattr(module, "multi_account_broker_manager", None)


def _broker_module() -> Any:
    try:
        return importlib.import_module("bot.broker_manager")
    except Exception:
        return None


def _kraken_mapping_entry(manager: Any) -> tuple[Any, Any]:
    mapping = getattr(manager, "_platform_brokers", None)
    if not isinstance(mapping, dict):
        return None, None
    for key, broker in list(mapping.items()):
        if _label(key) == "kraken":
            return key, broker
    return None, None


def _connected_platform_kraken_candidates(broker_module: Any) -> list[Any]:
    candidates: list[Any] = []
    seen: set[int] = set()

    global_instances = getattr(broker_module, "_PLATFORM_BROKER_INSTANCES", {})
    if isinstance(global_instances, dict):
        candidate = global_instances.get("kraken")
        if candidate is not None:
            candidates.append(candidate)

    kraken_cls = getattr(broker_module, "KrakenBroker", None)
    iterator = getattr(kraken_cls, "_iter_live", None)
    if callable(iterator):
        try:
            candidates.extend(list(iterator() or []))
        except Exception:
            pass

    result: list[Any] = []
    for broker in candidates:
        if broker is None or id(broker) in seen:
            continue
        seen.add(id(broker))
        if not _is_platform_account(broker):
            continue
        if not _actually_connected(broker):
            continue
        if bool(getattr(broker, "_hard_stopped", False)):
            continue
        result.append(broker)
    return result


def _write_registry_truth(manager: Any, broker_module: Any, key: Any, broker: Any) -> None:
    """Write instance-presence and connectivity to their separate registries."""
    name = _label(key)
    if not name or broker is None:
        return

    lock = getattr(broker_module, "_PLATFORM_BROKER_REGISTRY_LOCK", None)
    if lock is None:
        lock = _LOCK
    with lock:
        instances = getattr(broker_module, "_PLATFORM_BROKER_INSTANCES", None)
        presence = getattr(broker_module, "GLOBAL_PLATFORM_BROKERS", None)
        connected = getattr(broker_module, "_PLATFORM_BROKER_CONNECTED", None)
        if isinstance(instances, dict):
            instances[name] = broker
        if isinstance(presence, dict):
            # Presence is not connectivity.  Existing object => guard remains set.
            presence[name] = True
        if isinstance(connected, dict):
            connected[name] = _actually_connected(broker)

    local_connected = getattr(manager, "_platform_connected", None)
    if isinstance(local_connected, dict):
        local_connected[name] = _actually_connected(broker)


def _repair_manager_registry(manager: Any, broker_module: Any | None = None) -> bool:
    """Reconcile a split Kraken registry only with unambiguous live evidence."""
    if manager is None:
        return True
    broker_module = broker_module if broker_module is not None else _broker_module()
    if broker_module is None:
        return False

    mapping = getattr(manager, "_platform_brokers", None)
    if not isinstance(mapping, dict):
        return False

    key, local = _kraken_mapping_entry(manager)
    if key is None:
        # No manager Kraken entry: keep existing global semantics untouched.
        return True

    connected_candidates = _connected_platform_kraken_candidates(broker_module)
    canonical = local if _actually_connected(local) else None

    if canonical is not None:
        conflicting = [candidate for candidate in connected_candidates if candidate is not canonical]
        if conflicting:
            LOGGER.critical(
                "PLATFORM_KRAKEN_REGISTRY_V268_AMBIGUOUS marker=%s connected_candidates=%d "
                "manager_connected=true registry_mutated=false trading_fail_closed=true",
                MARKER,
                1 + len(conflicting),
            )
            return False
    elif len(connected_candidates) == 1:
        canonical = connected_candidates[0]
    elif len(connected_candidates) > 1:
        LOGGER.critical(
            "PLATFORM_KRAKEN_REGISTRY_V268_AMBIGUOUS marker=%s connected_candidates=%d "
            "manager_connected=false registry_mutated=false trading_fail_closed=true",
            MARKER,
            len(connected_candidates),
        )
        return False

    if canonical is None:
        # Disconnected truth remains disconnected.  Only repair the presence bit.
        if local is not None:
            _write_registry_truth(manager, broker_module, key, local)
        return True

    replaced = canonical is not local
    if replaced:
        registry_lock = getattr(manager, "_registry_meta_lock", None)
        if registry_lock is None:
            registry_lock = _LOCK
        with registry_lock:
            mapping[key] = canonical

    _write_registry_truth(manager, broker_module, key, canonical)

    if replaced:
        sync = getattr(manager, "_sync_reconnect_readiness", None)
        if callable(sync):
            try:
                sync(key, canonical)
            except Exception as exc:
                LOGGER.warning(
                    "PLATFORM_KRAKEN_REGISTRY_V268_SYNC_FAILED marker=%s error=%s:%s "
                    "broker_connected=%s trading_fail_closed=true",
                    MARKER,
                    type(exc).__name__,
                    exc,
                    str(_actually_connected(canonical)).lower(),
                )
                return False
        LOGGER.critical(
            "PLATFORM_KRAKEN_REGISTRY_V268_RECONCILED marker=%s old_id=%s canonical_id=%s "
            "unique_connected_platform_candidate=true user_brokers_excluded=true "
            "balance_fabricated=false capital_mutated=false freshness_extended=false "
            "nonce_policy_unchanged=true execution_authority_unchanged=true",
            MARKER,
            id(local) if local is not None else 0,
            id(canonical),
        )
    return True


def _patch_refresh_registry() -> bool:
    try:
        module = importlib.import_module("bot.multi_account_broker_manager")
        cls = getattr(module, "MultiAccountBrokerManager", None)
    except Exception:
        return False
    if not isinstance(cls, type):
        return False

    current = getattr(cls, "refresh_registry", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def refresh_registry_v268(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original(self, *args, **kwargs)
        broker_module = _broker_module()
        if broker_module is None or not _repair_manager_registry(self, broker_module):
            LOGGER.warning(
                "PLATFORM_KRAKEN_REGISTRY_V268_REFRESH_UNRESOLVED marker=%s "
                "trading_fail_closed=true",
                MARKER,
            )
        return result

    setattr(refresh_registry_v268, _PATCH_ATTR, True)
    setattr(refresh_registry_v268, "__wrapped__", original)
    cls.refresh_registry = refresh_registry_v268
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        installers = getattr(manifest, "_INSTALLERS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_platform_kraken_registry_liveness_v268"] = _READY_FLAG
        own = ("bot.runtime_platform_kraken_registry_liveness_v268_patch", "install_import_hook")
        if isinstance(installers, tuple) and own not in installers:
            manifest._INSTALLERS = tuple(installers) + (own,)
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        patched = _patch_refresh_registry()
        manager = _canonical_manager()
        repaired = _repair_manager_registry(manager) if manager is not None else True
        manifest = _patch_release_manifest()
        ready = bool(patched and repaired and manifest)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_PLATFORM_KRAKEN_REGISTRY_LIVENESS_V268_FAILED marker=%s "
                "refresh_patch=%s repaired=%s manifest=%s trading_fail_closed=true",
                MARKER,
                str(patched).lower(),
                str(repaired).lower(),
                str(manifest).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_PLATFORM_KRAKEN_REGISTRY_LIVENESS_V268 marker=%s ready=true "
            "instance_presence_separate_from_connectivity=true unique_connected_repair_only=true "
            "user_brokers_excluded=true capital_thresholds_unchanged=true freshness_extended=false "
            "nonce_policy_unchanged=true kill_switch_unchanged=true execution_proof_fabricated=false "
            "forced_trade=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_label",
    "_is_platform_account",
    "_actually_connected",
    "_connected_platform_kraken_candidates",
    "_write_registry_truth",
    "_repair_manager_registry",
    "_patch_refresh_registry",
    "_patch_release_manifest",
]
