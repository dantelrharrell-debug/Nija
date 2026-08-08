"""NIJA capital publication convergence v43.

Repairs a post-v42 capital-authority divergence observed during partial refreshes.
A coordinator snapshot may contain only the broker that completed in the current
bounded batch while the v37 sticky-success guard still holds fresh, independently
observed balances for other platform brokers. The legacy live-total v2 property
can then report the larger aggregate while CapitalAuthority.publish_snapshot()
overwrites the canonical typed snapshot with the smaller one-broker picture.

v43 restores one capital truth without inventing balances:

* current-cycle snapshot values always win;
* an omitted broker is added only when v37 has a fresh positive platform
  observation for that exact broker and the canonical platform broker is
  currently connected;
* disconnected brokers, stale observations, invalid values, user accounts, and
  unattributed aggregate totals are never promoted;
* real/usable/risk capital and broker_count are recomputed from the exact merged
  per-broker map before the authorized coordinator publish;
* after a typed snapshot exists, total_capital reads that canonical snapshot
  instead of max(snapshot, broker_sum, _last_updated_total), eliminating the
  contradictory read-time aggregate;
* the historical live-total v2 installer is wrapped so a later install cannot
  reintroduce the divergent property.

This patch does not connect brokers, fetch balances, force activation, clear any
risk state, or bypass capital freshness/readiness gates.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import math
import os
import sys
import threading
import time
from dataclasses import is_dataclass, replace
from functools import wraps
from types import ModuleType
from typing import Any, Dict, Iterable, Optional, Tuple

LOGGER = logging.getLogger("nija.capital_publication_convergence_v43")
MARKER = "20260807-capital-publication-convergence-v43"

_LOCK = threading.RLock()
_HOOK_FLAG = "_NIJA_CAPITAL_PUBLICATION_CONVERGENCE_V43_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_CAPITAL_PUBLICATION_CONVERGENCE_V43_IMPORTLIB_HOOK"
_CA_PATCH_ATTR = "_nija_capital_publication_convergence_v43_publish"
_TOTAL_PATCH_ATTR = "_nija_capital_publication_convergence_v43_total"
_LIVE_V2_PATCH_ATTR = "_nija_capital_publication_convergence_v43_live_v2"

_CA_NAMES = ("bot.capital_authority", "capital_authority")
_LIVE_V2_NAMES = (
    "bot.capital_authority_live_total_v2_patch",
    "capital_authority_live_total_v2_patch",
)
_GUARD_NAMES = (
    "nija_capital_refresh_stall_guard_v35_prebot",
    "bot.capital_refresh_stall_guard_v35",
    "capital_refresh_stall_guard_v35",
)
_BROKER_MODULE_NAMES = ("bot.broker_manager", "broker_manager")
_ALLOWED_BROKERS = ("coinbase", "okx", "kraken", "alpaca")


def _num(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(result) or result < 0.0:
        return 0.0
    return result


def _guard() -> Optional[ModuleType]:
    for name in _GUARD_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    return None


def _observation_ttl_s(guard: Optional[ModuleType]) -> float:
    configured = 90.0
    try:
        configured = float(os.environ.get("NIJA_V43_CAPITAL_OBSERVATION_TTL_S", "90") or "90")
    except (TypeError, ValueError):
        configured = 90.0
    configured = max(5.0, configured)
    if guard is None:
        return configured
    getter = getattr(guard, "_freshness_ttl_seconds", None)
    if callable(getter):
        try:
            return max(5.0, min(configured, float(getter())))
        except Exception:
            pass
    return configured


def _fresh_observation(broker_id: str) -> Tuple[bool, float, float, str]:
    """Return (ok, value, age_s, reason) from the canonical v37 guard state."""
    guard = _guard()
    if guard is None:
        return False, 0.0, float("inf"), "guard_unavailable"
    observations = getattr(guard, "_OBSERVATIONS", None)
    if not isinstance(observations, dict):
        return False, 0.0, float("inf"), "observations_unavailable"
    lock = getattr(guard, "_OBSERVATION_LOCK", None)
    if lock is None:
        observation = observations.get(broker_id)
    else:
        try:
            with lock:
                observation = observations.get(broker_id)
        except Exception:
            return False, 0.0, float("inf"), "observation_lock_failed"
    if observation is None:
        return False, 0.0, float("inf"), "observation_missing"

    value = _num(getattr(observation, "value", 0.0))
    observed_mono = _num(getattr(observation, "observed_monotonic", 0.0))
    if value <= 0.0 or observed_mono <= 0.0:
        return False, value, float("inf"), "observation_invalid"
    age_s = max(0.0, time.monotonic() - observed_mono)
    ttl_s = _observation_ttl_s(guard)
    if age_s > ttl_s:
        return False, value, age_s, f"observation_stale:{age_s:.3f}>{ttl_s:.3f}"
    return True, value, age_s, "fresh_v37_observation"


def _broker_name(instance: Any, key: Any = None) -> str:
    candidates = (
        getattr(getattr(instance, "broker_type", None), "value", None),
        getattr(getattr(instance, "broker_type", None), "name", None),
        getattr(instance, "name", None),
        getattr(instance, "broker_name", None),
        key,
        instance.__class__.__name__ if instance is not None else None,
    )
    for candidate in candidates:
        text = str(candidate or "").strip().lower()
        for broker_id in _ALLOWED_BROKERS:
            if broker_id in text:
                return broker_id
    return ""


def _is_platform(instance: Any) -> bool:
    account_type = getattr(instance, "account_type", None)
    text = str(getattr(account_type, "value", account_type) or "").strip().lower()
    return not text or "user" not in text


def _is_connected(instance: Any) -> bool:
    if instance is None or not _is_platform(instance):
        return False
    connected = getattr(instance, "connected", None)
    if connected is True:
        return True
    probe = getattr(instance, "is_connected", None)
    if callable(probe):
        try:
            return bool(probe())
        except Exception:
            return False
    return False


def _dict_instances(module: ModuleType) -> Iterable[Tuple[Any, Any]]:
    for attr in ("_PLATFORM_BROKER_INSTANCES", "GLOBAL_PLATFORM_BROKERS"):
        mapping = getattr(module, attr, None)
        if isinstance(mapping, dict):
            for key, value in list(mapping.items()):
                if value is not None:
                    yield key, value


def _connected_platform_instance(broker_id: str) -> Optional[Any]:
    seen: set[int] = set()
    for name in _BROKER_MODULE_NAMES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        for key, instance in _dict_instances(module):
            if id(instance) in seen:
                continue
            seen.add(id(instance))
            if _broker_name(instance, key) == broker_id and _is_connected(instance):
                return instance

        getter = getattr(module, "get_platform_broker", None)
        broker_type = getattr(module, "BrokerType", None)
        if callable(getter) and broker_type is not None:
            try:
                members = list(broker_type)
            except Exception:
                members = []
            for member in members:
                member_name = str(getattr(member, "value", None) or getattr(member, "name", "")).lower()
                if broker_id not in member_name:
                    continue
                try:
                    instance = getter(member)
                except Exception:
                    continue
                if instance is not None and _is_connected(instance):
                    return instance
    return None


def _augment_snapshot(snapshot: Any) -> Tuple[Any, Dict[str, Dict[str, Any]]]:
    """Return a canonicalized snapshot plus exact evidence for added brokers."""
    if not is_dataclass(snapshot):
        return snapshot, {}
    raw_balances = getattr(snapshot, "broker_balances", None)
    if not isinstance(raw_balances, dict):
        return snapshot, {}

    merged: Dict[str, float] = {
        str(key).strip().lower(): _num(value)
        for key, value in raw_balances.items()
        if _num(value) > 0.0
    }
    additions: Dict[str, Dict[str, Any]] = {}
    for broker_id in _ALLOWED_BROKERS:
        if broker_id in merged:
            continue
        ok, value, age_s, reason = _fresh_observation(broker_id)
        if not ok:
            continue
        instance = _connected_platform_instance(broker_id)
        if instance is None:
            LOGGER.info(
                "CAPITAL_PUBLICATION_V43_OMITTED marker=%s broker=%s reason=not_connected observation_age_s=%.3f",
                MARKER,
                broker_id,
                age_s,
            )
            continue
        merged[broker_id] = value
        additions[broker_id] = {
            "value": value,
            "age_s": age_s,
            "reason": reason,
            "class": instance.__class__.__name__,
        }

    if not additions:
        return snapshot, {}

    real = sum(merged.values())
    reserve_pct = _num(getattr(snapshot, "reserve_pct", 0.0))
    open_exposure = _num(getattr(snapshot, "open_exposure_usd", 0.0))
    usable = real * max(0.0, 1.0 - reserve_pct)
    risk = max(0.0, usable - open_exposure)
    broker_count = sum(1 for value in merged.values() if value > 0.0)
    try:
        expected = max(int(getattr(snapshot, "expected_brokers", 0) or 0), broker_count)
    except (TypeError, ValueError):
        expected = broker_count

    try:
        repaired = replace(
            snapshot,
            real_capital=real,
            usable_capital=usable,
            risk_capital=risk,
            broker_balances=dict(merged),
            broker_count=broker_count,
            expected_brokers=expected,
        )
    except Exception as exc:
        LOGGER.warning(
            "CAPITAL_PUBLICATION_V43_REPLACE_FAILED marker=%s err=%s",
            MARKER,
            exc,
        )
        return snapshot, {}

    LOGGER.critical(
        "CAPITAL_PUBLICATION_V43_AUGMENTED marker=%s original_total=%.2f repaired_total=%.2f original_brokers=%s repaired_brokers=%s additions=%s",
        MARKER,
        _num(getattr(snapshot, "real_capital", 0.0)),
        real,
        sorted(str(key) for key in raw_balances),
        sorted(merged),
        {key: round(row["value"], 8) for key, row in additions.items()},
    )
    return repaired, additions


def _canonical_total_property(self: Any) -> float:
    lock = getattr(self, "_lock", None)

    def _read() -> float:
        snapshot = getattr(self, "_last_typed_snapshot", None)
        if snapshot is not None:
            return _num(getattr(snapshot, "real_capital", 0.0))
        if bool(getattr(self, "_hydrated", False)) or bool(getattr(self, "_warm_start", False)):
            balances = getattr(self, "_broker_balances", {}) or {}
            if isinstance(balances, dict):
                return sum(_num(value) for value in balances.values())
        return 0.0

    if lock is None:
        return _read()
    try:
        with lock:
            return _read()
    except Exception:
        return _read()


setattr(_canonical_total_property, _TOTAL_PATCH_ATTR, True)


def _ensure_total_property(cls: type) -> None:
    current = getattr(cls, "total_capital", None)
    fget = getattr(current, "fget", current)
    if getattr(fget, _TOTAL_PATCH_ATTR, False):
        return
    cls.total_capital = property(_canonical_total_property)
    LOGGER.critical("CAPITAL_PUBLICATION_V43_TOTAL_CANONICALIZED marker=%s class=%s", MARKER, cls.__name__)


def _patch_capital_authority(module: ModuleType) -> bool:
    cls = getattr(module, "CapitalAuthority", None)
    if not isinstance(cls, type):
        return False
    _ensure_total_property(cls)
    original = getattr(cls, "publish_snapshot", None)
    if not callable(original):
        return False
    if getattr(original, _CA_PATCH_ATTR, False):
        return True

    @wraps(original)
    def publish_snapshot(self: Any, snapshot: Any, writer_id: str) -> bool:
        authorized = str(getattr(self, "_AUTHORIZED_WRITER_ID", "") or "")
        candidate = snapshot
        additions: Dict[str, Dict[str, Any]] = {}
        if writer_id == authorized:
            candidate, additions = _augment_snapshot(snapshot)
        accepted = bool(original(self, candidate, writer_id=writer_id))
        if accepted:
            _ensure_total_property(self.__class__)
            if additions:
                candidate_ts = getattr(candidate, "computed_at", None)
                lock = getattr(self, "_lock", None)
                try:
                    if lock is None:
                        if getattr(self, "last_updated", None) == candidate_ts:
                            self._last_updated_total = _num(getattr(candidate, "real_capital", 0.0))
                    else:
                        with lock:
                            if getattr(self, "last_updated", None) == candidate_ts:
                                self._last_updated_total = _num(getattr(candidate, "real_capital", 0.0))
                except Exception:
                    pass
                LOGGER.critical(
                    "CAPITAL_PUBLICATION_V43_COMMITTED marker=%s total=%.2f broker_count=%s additions=%s",
                    MARKER,
                    _num(getattr(candidate, "real_capital", 0.0)),
                    getattr(candidate, "broker_count", "unknown"),
                    sorted(additions),
                )
        return accepted

    setattr(publish_snapshot, _CA_PATCH_ATTR, True)
    cls.publish_snapshot = publish_snapshot
    LOGGER.critical("CAPITAL_PUBLICATION_V43_CA_PATCHED marker=%s module=%s", MARKER, module.__name__)
    return True


def _patch_live_total_v2(module: ModuleType) -> bool:
    original = getattr(module, "_patch_module", None)
    if not callable(original):
        return False
    if getattr(original, _LIVE_V2_PATCH_ATTR, False):
        return True

    @wraps(original)
    def patch_module(target: ModuleType) -> bool:
        result = bool(original(target))
        try:
            _patch_capital_authority(target)
        except Exception as exc:
            LOGGER.warning(
                "CAPITAL_PUBLICATION_V43_LIVE_V2_RECANONICALIZE_FAILED marker=%s err=%s",
                MARKER,
                exc,
            )
        return result

    setattr(patch_module, _LIVE_V2_PATCH_ATTR, True)
    module._patch_module = patch_module
    LOGGER.critical("CAPITAL_PUBLICATION_V43_LIVE_V2_PATCHED marker=%s module=%s", MARKER, module.__name__)
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in _CA_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_capital_authority(module) or changed
    seen.clear()
    for name in _LIVE_V2_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_live_total_v2(module) or changed
    return changed


def _interesting(name: str) -> bool:
    text = str(name or "")
    return any(
        text.endswith(suffix)
        for suffix in (
            "capital_authority",
            "capital_authority_live_total_v2_patch",
            "capital_refresh_stall_guard_v35",
            "broker_manager",
        )
    )


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if _interesting(name):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module(name: str, package: Optional[str] = None):
                result = original_import_module(name, package)
                if _interesting(name):
                    _patch_loaded()
                return result

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        os.environ["NIJA_CAPITAL_PUBLICATION_CONVERGENCE_V43_INSTALLED"] = "1"
        LOGGER.critical(
            "CAPITAL_PUBLICATION_CONVERGENCE_V43_INSTALLED marker=%s fail_closed=true unattributed_total_promoted=false disconnected_brokers_promoted=false",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_augment_snapshot",
    "_fresh_observation",
    "_patch_capital_authority",
    "_patch_live_total_v2",
]
