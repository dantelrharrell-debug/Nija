"""Converge same-cycle capital refresh provenance across import aliases (v229).

Production evidence on 2026-08-25 showed a canonical capital publication rejected
as ``incomplete_broker_aggregation:2/3`` while the stalled-writer diagnostic
reported ``valid_brokers=3`` and position sync remained 3/3. The v209 zero
balance completeness repair is intentionally fail closed, but its provenance
reader returned the first loaded stall-guard alias even when that alias did not
own the current thread's active refresh context. A second alias could therefore
hold the real same-cycle ``live_brokers`` evidence while v209 saw an empty/default
status and declined the legitimate zero-balance entry.

v229 changes provenance selection. It inspects every known stall-guard alias,
considers only aliases whose thread-local refresh context is actively in flight
on the publishing thread, deduplicates identical module objects, and merges
evidence conservatively. Exclusion or disagreement always wins over a live
observation. The existing v209 rules remain authoritative: only an exact
same-cycle live zero may restore a missing broker key; positive balances are
never synthesized; timeout/error/stale/unknown brokers remain excluded.

After its provenance hooks attach, v229 installs v230 so every distinct loaded
CapitalAuthority publisher alias receives the same v209 augmentation boundary.
Capital amounts, freshness, completeness thresholds, writer/nonce/risk/
kill-switch, order/fill and activation gates remain unchanged.
"""
from __future__ import annotations

import importlib
import logging
import math
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_capital_provenance_alias_convergence_v229")
MARKER = "20260825-runtime-capital-provenance-alias-convergence-v229"
RELEASE_ID = "20260825-runtime-convergence-v229"
_READY_FLAG = "NIJA_RUNTIME_CAPITAL_PROVENANCE_ALIAS_V229_READY"
_PATCH_ATTR = "_nija_runtime_capital_provenance_alias_v229"
_LOCK = threading.RLock()
_GUARD_NAMES = (
    "nija_capital_refresh_stall_guard_v35_prebot",
    "bot.capital_refresh_stall_guard_v35",
    "capital_refresh_stall_guard_v35",
)


def _key(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip().lower()


def _row_scalar(row: Any) -> float | None:
    try:
        if isinstance(row, dict):
            value = float(row.get("value", 0.0))
        else:
            value = float(row)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value) or value < 0.0:
        return None
    return value


def _active_guard_statuses() -> list[tuple[str, ModuleType, dict[str, Any]]]:
    rows: list[tuple[str, ModuleType, dict[str, Any]]] = []
    seen: set[int] = set()
    for name in _GUARD_NAMES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        context = getattr(module, "_REFRESH_CONTEXT", None)
        if context is None or not bool(getattr(context, "in_refresh", False)):
            continue
        getter = getattr(module, "current_refresh_fallback_status", None)
        if not callable(getter):
            continue
        try:
            status = dict(getter())
        except Exception as exc:
            LOGGER.warning(
                "CAPITAL_PROVENANCE_ALIAS_V229_READ_FAILED marker=%s alias=%s error=%s:%s "
                "trading_fail_closed=true",
                MARKER, name, type(exc).__name__, exc,
            )
            continue
        rows.append((name, module, status))
    return rows


def _merged_active_guard_status() -> dict[str, Any]:
    rows = _active_guard_statuses()
    if not rows:
        return {}

    live: dict[str, dict[str, Any]] = {}
    excluded: dict[str, dict[str, Any]] = {}
    fallbacks: dict[str, dict[str, Any]] = {}
    live_values: dict[str, float] = {}
    conflicts: set[str] = set()
    used_fallback = False

    for alias, _module, status in rows:
        used_fallback = used_fallback or bool(status.get("used_fallback", False))
        for raw_key, raw_row in dict(status.get("brokers", {}) or {}).items():
            broker = _key(raw_key)
            if broker and broker not in fallbacks:
                fallbacks[broker] = dict(raw_row or {}) if isinstance(raw_row, dict) else {"value": raw_row}

        for raw_key, raw_row in dict(status.get("excluded_brokers", {}) or {}).items():
            broker = _key(raw_key)
            if not broker:
                continue
            row = dict(raw_row or {}) if isinstance(raw_row, dict) else {"reason": str(raw_row)}
            row.setdefault("reason", "excluded_by_active_alias")
            row["alias"] = alias
            excluded[broker] = row

        for raw_key, raw_row in dict(status.get("live_brokers", {}) or {}).items():
            broker = _key(raw_key)
            scalar = _row_scalar(raw_row)
            if not broker or scalar is None:
                continue
            previous = live_values.get(broker)
            if previous is not None and not math.isclose(previous, scalar, rel_tol=0.0, abs_tol=1e-12):
                conflicts.add(broker)
                excluded[broker] = {
                    "reason": "active_alias_value_conflict",
                    "first_value": previous,
                    "second_value": scalar,
                    "alias": alias,
                    "cached_valid": False,
                }
                continue
            live_values[broker] = scalar
            row = dict(raw_row or {}) if isinstance(raw_row, dict) else {"value": scalar}
            row["value"] = scalar
            row["alias"] = alias
            live[broker] = row

    for broker in set(excluded) | conflicts:
        live.pop(broker, None)

    all_recent = bool(
        used_fallback
        and fallbacks
        and not excluded
        and all(bool(row.get("cached_valid", row.get("observed", False))) for row in fallbacks.values())
    )
    result = {
        "used_fallback": used_fallback,
        "all_recent": all_recent,
        "brokers": fallbacks,
        "excluded_brokers": excluded,
        "live_brokers": live,
        "source": "v229_active_alias_merge",
        "active_aliases": tuple(alias for alias, _module, _status in rows),
    }
    if len(rows) > 1 or conflicts:
        LOGGER.warning(
            "CAPITAL_PROVENANCE_ALIAS_V229_MERGED marker=%s aliases=%s live=%s excluded=%s conflicts=%s "
            "exclusion_wins=true stale_aliases_ignored=true capital_mutated=false trading_fail_closed=true",
            MARKER, list(result["active_aliases"]), sorted(live), sorted(excluded), sorted(conflicts),
        )
    return result


def _patch_v209() -> bool:
    try:
        v209 = importlib.import_module("bot.runtime_zero_balance_completeness_v209_patch")
    except Exception:
        return False

    installer = getattr(v209, "install", None)
    if callable(installer) and installer() is False:
        return False

    current_guard = getattr(v209, "_guard_status", None)
    if not callable(current_guard):
        return False
    if not bool(getattr(current_guard, _PATCH_ATTR, False)):
        @wraps(current_guard)
        def guard_v229() -> dict[str, Any]:
            active = _merged_active_guard_status()
            if active:
                return active
            return {}

        setattr(guard_v229, _PATCH_ATTR, True)
        setattr(guard_v229, "__wrapped__", current_guard)
        v209._guard_status = guard_v229

    current_augment = getattr(v209, "_augment_snapshot", None)
    if not callable(current_augment):
        return False
    if not bool(getattr(current_augment, _PATCH_ATTR, False)):
        @wraps(current_augment)
        def augment_v229(snapshot: Any):
            balances = dict(getattr(snapshot, "broker_balances", {}) or {})
            before_keys = sorted({_key(key) for key in balances if _key(key)})
            try:
                expected = max(0, int(getattr(snapshot, "expected_brokers", 0) or 0))
            except (TypeError, ValueError):
                expected = 0
            augmented, additions = current_augment(snapshot)
            if expected > len(before_keys):
                status = _merged_active_guard_status()
                live_keys = sorted({_key(key) for key in dict(status.get("live_brokers", {}) or {}) if _key(key)})
                excluded_keys = sorted({_key(key) for key in dict(status.get("excluded_brokers", {}) or {}) if _key(key)})
                candidate_missing = sorted((set(live_keys) | set(excluded_keys)) - set(before_keys))
                LOGGER.warning(
                    "CAPITAL_COMPLETENESS_V229_DIAGNOSTIC marker=%s expected=%d entries_before=%d "
                    "snapshot_keys=%s live_keys=%s excluded_keys=%s candidate_missing=%s additions=%s "
                    "positive_balance_fabricated=false timeout_exclusions_preserved=true "
                    "freshness_extended=false completeness_threshold_unchanged=true trading_fail_closed=true",
                    MARKER, expected, len(before_keys), before_keys, live_keys, excluded_keys,
                    candidate_missing, list(additions),
                )
            return augmented, additions

        setattr(augment_v229, _PATCH_ATTR, True)
        setattr(augment_v229, "__wrapped__", current_augment)
        v209._augment_snapshot = augment_v229

    return bool(
        getattr(getattr(v209, "_guard_status", None), _PATCH_ATTR, False)
        and getattr(getattr(v209, "_augment_snapshot", None), _PATCH_ATTR, False)
    )


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_capital_provenance_alias_v229"] = _READY_FLAG
        return True
    except Exception:
        return False


def _install_v230() -> bool:
    try:
        module = importlib.import_module("bot.runtime_capital_authority_alias_v230_patch")
        installer = getattr(module, "install", None)
        return bool(callable(installer) and installer())
    except Exception as exc:
        LOGGER.error(
            "CAPITAL_AUTHORITY_ALIAS_V230_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
            MARKER, type(exc).__name__, exc,
        )
        return False


def install() -> bool:
    with _LOCK:
        v209_ok = _patch_v209()
        manifest_ok = _patch_release_manifest()
        v230_ok = bool(v209_ok and manifest_ok and _install_v230())
        ready = bool(v209_ok and manifest_ok and v230_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        LOGGER.critical(
            "RUNTIME_CAPITAL_PROVENANCE_ALIAS_V229 marker=%s ready=%s "
            "active_refresh_alias_only=true duplicate_module_dedup=true exclusion_wins=true "
            "alias_conflict_fail_closed=true same_cycle_live_zero_rule_preserved=true "
            "publisher_alias_v230=%s positive_balance_fabricated=false stale_balance_reused=false "
            "freshness_extended=false completeness_threshold_unchanged=true "
            "writer_nonce_risk_killswitch_order_fill_gates_unchanged=true forced_activation=false "
            "safety_gates_bypassed=false",
            MARKER, str(ready).lower(), str(v230_ok).lower(),
        )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_active_guard_statuses",
    "_merged_active_guard_status",
    "_patch_v209",
    "_install_v230",
]
