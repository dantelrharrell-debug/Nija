"""Repair current-snapshot freshness during capital pipeline publication.

The coordinator historically copied the age of the *previous* CapitalAuthority
snapshot into ``CapitalSnapshot.snapshot_age_s`` and then used that value to set
``is_fresh``.  On a cold start the previous age is infinite, so a snapshot built
from balances fetched in the current pipeline tick is incorrectly marked stale.

This module installs a narrow import hook that corrects the observable freshness
fields on ``CapitalSnapshot`` without weakening broker-count, capital, confidence,
or TTL requirements.  It is intentionally loaded by the canonical launcher before
application imports.
"""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import logging
import os
import sys
import time
from datetime import datetime, timezone
from types import ModuleType
from typing import Any, Optional

LOGGER = logging.getLogger("nija.current_snapshot_freshness_repair")
MARKER = "20260727-current-snapshot-freshness-v1"
_TARGETS = {"bot.capital_flow_state_machine", "capital_flow_state_machine"}
_INSTALLED = False
_PATCHED_CLASSES: set[int] = set()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUE


def _utc_age_seconds(value: Any) -> float:
    if not isinstance(value, datetime):
        return float("inf")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    try:
        return max(0.0, (datetime.now(timezone.utc) - value.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return float("inf")


def _current_snapshot_is_fresh(snapshot: Any) -> bool:
    """Return True only when the current snapshot itself satisfies freshness."""

    try:
        original_stale = bool(object.__getattribute__(snapshot, "is_stale"))
        original_age = float(object.__getattribute__(snapshot, "snapshot_age_s"))
        computed_at = object.__getattribute__(snapshot, "computed_at")
        real_capital = float(object.__getattribute__(snapshot, "real_capital"))
        broker_count = int(object.__getattribute__(snapshot, "broker_count"))
        expected_brokers = int(object.__getattribute__(snapshot, "expected_brokers"))
        confidence = object.__getattribute__(snapshot, "confidence")
        freshness_score = float(getattr(confidence, "freshness_score", 0.0))
    except Exception:
        return False

    # Preserve an already-fresh result exactly as produced by the coordinator.
    if not original_stale:
        return True

    try:
        ttl_s = max(1.0, float(os.environ.get("NIJA_CAPITAL_FRESHNESS_TTL_S", "90") or 90.0))
    except (TypeError, ValueError):
        ttl_s = 90.0

    current_age = _utc_age_seconds(computed_at)
    opportunistic = _truthy("NIJA_OPPORTUNISTIC_CAPITAL_MODE") or _truthy(
        "NIJA_BROKER_INDEPENDENT_LIVE_EXECUTION"
    )
    required_brokers = 1 if opportunistic else max(1, expected_brokers)

    # Override only the known defect: the stored age refers to the previous
    # snapshot while the current snapshot was computed within the TTL from a
    # successful, confidence-bearing broker fetch.
    return (
        original_age > ttl_s
        and current_age <= ttl_s
        and real_capital > 0.0
        and broker_count >= required_brokers
        and freshness_score > 0.0
    )


def _patch_snapshot_class(module: ModuleType) -> bool:
    cls = getattr(module, "CapitalSnapshot", None)
    if not isinstance(cls, type) or id(cls) in _PATCHED_CLASSES:
        return False

    original_getattribute = cls.__getattribute__

    def _getattribute(self: Any, name: str) -> Any:
        if name == "snapshot_age_s":
            try:
                computed_at = object.__getattribute__(self, "computed_at")
                current_age = _utc_age_seconds(computed_at)
                stored_age = float(object.__getattribute__(self, "snapshot_age_s"))
                if current_age != float("inf") and stored_age > current_age:
                    return current_age
            except Exception:
                pass
        elif name in {"is_fresh", "is_stale"}:
            try:
                repaired_fresh = _current_snapshot_is_fresh(self)
                if repaired_fresh:
                    return name == "is_fresh"
            except Exception:
                pass
        return original_getattribute(self, name)

    cls.__getattribute__ = _getattribute
    _PATCHED_CLASSES.add(id(cls))
    LOGGER.critical(
        "CURRENT_SNAPSHOT_FRESHNESS_REPAIR_PATCHED marker=%s module=%s",
        MARKER,
        module.__name__,
    )
    return True


class _RepairLoader(importlib.abc.Loader):
    def __init__(self, wrapped: importlib.abc.Loader) -> None:
        self._wrapped = wrapped

    def create_module(self, spec):
        creator = getattr(self._wrapped, "create_module", None)
        return creator(spec) if callable(creator) else None

    def exec_module(self, module: ModuleType) -> None:
        self._wrapped.exec_module(module)
        _patch_snapshot_class(module)


class _RepairFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Optional[list[str]], target=None):
        if fullname not in _TARGETS:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None or isinstance(spec.loader, _RepairLoader):
            return spec
        spec.loader = _RepairLoader(spec.loader)
        return spec


def install_import_hook() -> bool:
    global _INSTALLED
    if _INSTALLED:
        return True

    for name in _TARGETS:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch_snapshot_class(module)

    sys.meta_path.insert(0, _RepairFinder())
    _INSTALLED = True
    os.environ["NIJA_CURRENT_SNAPSHOT_FRESHNESS_REPAIR_INSTALLED"] = "1"
    LOGGER.critical(
        "CURRENT_SNAPSHOT_FRESHNESS_REPAIR_INSTALLED marker=%s",
        MARKER,
    )
    return True


install = install_import_hook
