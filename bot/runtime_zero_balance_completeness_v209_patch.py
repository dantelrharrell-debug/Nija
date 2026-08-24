"""Preserve confirmed zero-balance venues in canonical capital completeness (v209).

Production on 2026-08-24 showed the canonical platform broker registry healthy at
3/3 while capital publication repeatedly failed closed as
``incomplete_broker_aggregation:2/3``.  The missing venue was not disconnected:
the bounded capital refresh had a live current observation for the venue whose
balance was exactly 0.00.  ``CapitalRefreshCoordinator`` drops zero-valued rows
before building ``CapitalSnapshot``, while v170/v199 intentionally defines
completeness by broker entries and explicitly allows a zero-balance entry to
count toward the required broker set.  The mismatch causes a truthful 3-broker
refresh to be represented as 2/3, lets the prior publication expire, and then
blocks the heartbeat/order path on ``capital_snapshot_stale``.

v209 repairs only that representation mismatch.  Immediately before canonical
``publish_snapshot`` processing, it restores a missing broker key with value
0.0 only when the same in-flight bounded refresh reports that broker in
``live_brokers`` with an exact non-negative scalar of zero and does not report it
in ``excluded_brokers``.  Timeout/error sentinels therefore remain excluded.
Positive missing balances are never synthesized, stale observations are never
promoted, capital totals are unchanged, and the existing 3/3 completeness,
freshness, writer, nonce, risk, kill-switch, order, fill, and activation gates
remain unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from dataclasses import replace
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_zero_balance_completeness_v209")
MARKER = "20260824-zero-balance-completeness-v209"
RELEASE_ID = "20260824-runtime-convergence-v209"
_READY_FLAG = "NIJA_RUNTIME_ZERO_BALANCE_COMPLETENESS_V209_READY"
_PATCH_ATTR = "_nija_runtime_zero_balance_completeness_v209"
_LOCK = threading.RLock()
_GUARD_NAMES = (
    "nija_capital_refresh_stall_guard_v35_prebot",
    "bot.capital_refresh_stall_guard_v35",
    "capital_refresh_stall_guard_v35",
)


def _guard_status() -> dict[str, Any]:
    """Return current same-cycle bounded-fetch provenance, or an empty dict."""
    for name in _GUARD_NAMES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        getter = getattr(module, "current_refresh_fallback_status", None)
        if not callable(getter):
            continue
        try:
            return dict(getter())
        except Exception:
            return {}
    return {}


def _zero_live_brokers(snapshot: Any) -> tuple[str, ...]:
    """Return missing brokers proven live at exactly 0.0 in this refresh cycle."""
    balances = getattr(snapshot, "broker_balances", None)
    if not isinstance(balances, dict):
        return ()

    status = _guard_status()
    live = dict(status.get("live_brokers", {}) or {})
    excluded = dict(status.get("excluded_brokers", {}) or {})
    if not live:
        return ()

    existing = {
        str(getattr(key, "value", key) or "").strip().lower()
        for key in balances
        if str(getattr(key, "value", key) or "").strip()
    }
    result: list[str] = []
    for raw_key, row in live.items():
        broker_key = str(getattr(raw_key, "value", raw_key) or "").strip().lower()
        if not broker_key or broker_key in existing or broker_key in excluded:
            continue
        try:
            value = float((row or {}).get("value", 0.0))
        except (TypeError, ValueError, AttributeError, OverflowError):
            continue
        if value == 0.0:
            result.append(broker_key)
    return tuple(sorted(set(result)))


def _augment_snapshot(snapshot: Any) -> tuple[Any, tuple[str, ...]]:
    additions = _zero_live_brokers(snapshot)
    if not additions:
        return snapshot, ()

    balances = dict(getattr(snapshot, "broker_balances", {}) or {})
    for broker_key in additions:
        balances[broker_key] = 0.0

    try:
        augmented = replace(
            snapshot,
            broker_balances=balances,
            broker_count=len(balances),
        )
    except Exception:
        # CapitalSnapshot is a frozen dataclass in production.  If an unexpected
        # snapshot type reaches this repair, fail closed by leaving it unchanged.
        return snapshot, ()

    return augmented, additions


def _patch_capital_authority() -> bool:
    try:
        module = importlib.import_module("bot.capital_authority")
    except Exception:
        return False
    cls = getattr(module, "CapitalAuthority", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "publish_snapshot", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def publish_v209(self: Any, snapshot: Any, writer_id: str) -> bool:
        augmented, additions = _augment_snapshot(snapshot)
        if additions:
            before = len(dict(getattr(snapshot, "broker_balances", {}) or {}))
            after = len(dict(getattr(augmented, "broker_balances", {}) or {}))
            LOGGER.critical(
                "ZERO_BALANCE_COMPLETENESS_V209_RESTORED marker=%s brokers=%s "
                "entries_before=%d entries_after=%d real_capital_unchanged=%.8f "
                "same_cycle_live_observation_required=true excluded_timeout_brokers_blocked=true "
                "positive_balance_fabricated=false freshness_extended=false "
                "publication_expiry_extended=false completeness_threshold_unchanged=true "
                "execution_authority_granted=false forced_trade=false safety_gates_bypassed=false",
                MARKER,
                list(additions),
                before,
                after,
                float(getattr(snapshot, "real_capital", 0.0) or 0.0),
            )
        return bool(current(self, augmented, writer_id))

    setattr(publish_v209, _PATCH_ATTR, True)
    # ``wraps`` intentionally preserves inner v170/v178 patch markers so their
    # idempotence checks do not wrap outside v209 later and bypass augmentation.
    cls.publish_snapshot = publish_v209
    return bool(getattr(cls.publish_snapshot, _PATCH_ATTR, False))


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_zero_balance_completeness_v209"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        authority_ok = _patch_capital_authority()
        manifest_ok = _patch_release_manifest()
        ready = bool(authority_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "ZERO_BALANCE_COMPLETENESS_V209_FAILED marker=%s authority=%s manifest=%s "
                "trading_fail_closed=true",
                MARKER,
                str(authority_ok).lower(),
                str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "ZERO_BALANCE_COMPLETENESS_V209_READY marker=%s ready=true "
            "same_cycle_live_zero_only=true timeout_exclusions_preserved=true "
            "positive_balance_fabricated=false capital_total_unchanged=true "
            "freshness_ttl_unchanged=true completeness_threshold_unchanged=true "
            "writer_nonce_risk_killswitch_order_fill_gates_unchanged=true "
            "forced_activation=false safety_gates_bypassed=false",
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
    "_guard_status",
    "_zero_live_brokers",
    "_augment_snapshot",
    "_patch_capital_authority",
]
