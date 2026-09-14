"""Converge all-account coverage onto the current canonical broker object v374/v416.

v90 may rebuild a Kraken user broker after startup. During that handoff the
canonical manager can briefly contain both the retired broker object and the
new authenticated broker in different compatibility registries. v281 builds
its denominator from all of those registries, and a later stale registry entry
can overwrite the current connected object for the same account key. The
result is a false ``disconnected`` or stale-snapshot coverage blocker even while
v86/v90 have already authenticated and reconciled the replacement broker.

v374 changes only broker-object selection for duplicate account keys. v416
closes a remaining tie-break defect in that selection: the original score
classified every historical v285 timestamp as equally "current", so two
connected/adopted broker objects could tie and leave a retired stale object
selected indefinitely. v416 prefers a genuinely current, successful v285
snapshot under the existing unchanged v285 TTL, then the newest authoritative
snapshot timestamp/generation. Completed v285 fetch failure is never considered
current. If no current snapshot exists, existing startup fetch/adoption truth
continues to break the tie fail-closed.

This module keeps v281's complete enabled-account denominator, performs no
broker I/O, does not mutate manager registries, does not extend snapshot TTLs,
and never fabricates connectivity, position proof, protection, capital, nonce,
writer authority, fills, or execution readiness. Platform identities are
unchanged.

The convergence chain deliberately reasserts v289 first so every canonical
platform/user broker owns account-scoped position state and stale tracker rows
can only be removed from a fresh authoritative snapshot. v377 then materializes
NIJA's symbol-only PositionTracker interface into universal local position rows.

Kraken-native backup bootstrap is intentionally independent from the later v375
universal-policy reassertion: v381 bridges synthetic Kraken margin symbols to
exchange pair lookups and starts v380 while the already-live v366/v367/v371
margin protection stack remains authoritative. v379's observational registered-
user proof monitor is also started before the later policy reassertion; it stays
PENDING until v281 exposes complete four-way proof and never manufactures a
trade or fill. v375 establishes the universal four-way contract, v390 converges
its synthesized exits onto the research-informed ATR/R-multiple policy, and v376
then verifies universal broker/asset scope for new exposure. Existing software
exits remain fail-closed throughout.
"""
from __future__ import annotations

import importlib
import logging
import os
import time
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_all_account_broker_identity_convergence_v374")
MARKER = "20260905-all-account-broker-identity-convergence-v374"
V416_MARKER = "20260914-user-broker-fresh-snapshot-selection-v416"
_READY_FLAG = "NIJA_RUNTIME_ALL_ACCOUNT_BROKER_IDENTITY_CONVERGENCE_V374_READY"
_PATCH_ATTR = "_nija_all_account_broker_identity_convergence_v374"


def _connected(broker: Any) -> bool:
    if broker is None:
        return False
    try:
        value = getattr(broker, "connected", False)
        return bool(value() if callable(value) else value)
    except Exception:
        return False


def _snapshot_ttl_s() -> float:
    """Read the same bounded v285 TTL without changing it."""
    try:
        value = float(os.environ.get("NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S", "90") or 90.0)
    except (TypeError, ValueError):
        value = 90.0
    return max(15.0, min(600.0, value))


def _score(broker: Any) -> tuple[int, int, float, int, int, int]:
    """Rank duplicate user brokers by already-existing authoritative truth.

    Fresh v285 truth deliberately outranks transient startup fetch/adoption
    flags. This matters during an exact authenticated refresh, when legacy
    reconciliation can briefly clear those flags while the prior v285 snapshot
    is still current. A completed v285 failure is never promoted because
    ``_nija_authoritative_position_snapshot_fetch_ok_v285`` must remain true.
    """
    if broker is None:
        return (0, 0, 0.0, 0, 0, 0)

    connected = 1 if _connected(broker) else 0
    fetch = 1 if getattr(broker, "_startup_position_sync_fetch_ok", None) is True else 0
    adopted = 1 if getattr(broker, "_startup_position_sync_adopted", None) is True else 0

    snapshot_current = 0
    snapshot_at = 0.0
    generation = 0
    try:
        snapshot_at = float(
            getattr(broker, "_nija_authoritative_position_snapshot_at_monotonic_v285", 0.0) or 0.0
        )
        generation = int(
            getattr(broker, "_nija_authoritative_position_snapshot_generation_v285", 0) or 0
        )
        snapshot_fetch_ok = (
            getattr(broker, "_nija_authoritative_position_snapshot_fetch_ok_v285", None) is True
        )
        rows_present = hasattr(broker, "_nija_authoritative_position_snapshot_rows_v285")
        age_s = max(0.0, time.monotonic() - snapshot_at) if snapshot_at > 0.0 else float("inf")
        snapshot_current = int(
            connected
            and snapshot_fetch_ok
            and rows_present
            and snapshot_at > 0.0
            and age_s <= _snapshot_ttl_s()
        )
    except Exception:
        snapshot_current = 0
        snapshot_at = 0.0
        generation = 0

    # Ordering is intentional: connected + genuinely current authoritative
    # snapshot wins first; newest observation breaks ties. Startup flags and
    # generation are secondary truth signals only.
    return (connected, snapshot_current, snapshot_at, fetch, adopted, generation)


def _label(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _user_key(user_id: Any, broker_type: Any) -> str:
    user = str(user_id or "").strip()
    venue = _label(broker_type)
    return f"user:{user}:{venue}" if user and venue else ""


def _candidate_user_brokers(manager: Any) -> dict[str, list[Any]]:
    candidates: dict[str, list[Any]] = {}

    def add(key: str, broker: Any) -> None:
        if not key or broker is None:
            return
        bucket = candidates.setdefault(key, [])
        if all(existing is not broker for existing in bucket):
            bucket.append(broker)

    try:
        all_users = getattr(manager, "_all_user_brokers", {}) or {}
        for raw_key, broker in tuple(all_users.items()):
            if isinstance(raw_key, tuple) and len(raw_key) == 2:
                add(_user_key(raw_key[0], raw_key[1]), broker)
    except Exception:
        pass

    try:
        user_brokers = getattr(manager, "user_brokers", {}) or {}
        for user_id, broker_map in tuple(user_brokers.items()):
            if not isinstance(broker_map, Mapping):
                continue
            for broker_type, broker in tuple(broker_map.items()):
                add(_user_key(user_id, broker_type), broker)
    except Exception:
        pass

    return candidates


def _patch_v281() -> bool:
    v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
    current = getattr(v281, "_expected_accounts", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def expected_accounts_v374(manager: Any) -> dict[str, Any]:
        expected = dict(current(manager) or {})
        if manager is None or not expected:
            return expected
        candidates = _candidate_user_brokers(manager)
        replacements: list[tuple[str, tuple[Any, ...], tuple[Any, ...]]] = []
        for account, broker in tuple(expected.items()):
            if not str(account).startswith("user:"):
                continue
            pool = list(candidates.get(str(account), ()))
            if broker is not None and all(item is not broker for item in pool):
                pool.append(broker)
            if not pool:
                continue
            best = max(pool, key=_score)
            if best is not broker and _score(best) > _score(broker):
                replacements.append((str(account), _score(broker), _score(best)))
                expected[account] = best
        if replacements:
            LOGGER.critical(
                "ALL_ACCOUNT_BROKER_IDENTITY_V416_FRESH_RECONCILED marker=%s base_marker=%s replacements=%s "
                "current_v285_snapshot_preferred=true newest_snapshot_tiebreak=true snapshot_ttl_unchanged=true "
                "completed_fetch_failure_not_current=true broker_io=false registry_mutation=false "
                "connectivity_fabricated=false position_proof_fabricated=false protection_fabricated=false "
                "safety_gates_bypassed=false",
                V416_MARKER,
                MARKER,
                replacements,
            )
        return expected

    setattr(expected_accounts_v374, _PATCH_ATTR, True)
    setattr(tsm := expected_accounts_v374, "_nija_user_broker_fresh_snapshot_selection_v416", True)
    setattr(tsm, "__wrapped__", current)
    v281._expected_accounts = expected_accounts_v374
    return True


def _install_module(module_name: str, label: str) -> bool:
    try:
        module = importlib.import_module(module_name)
        installer = getattr(module, "install_import_hook", None)
        if not callable(installer):
            installer = getattr(module, "install", None)
        return bool(callable(installer) and installer())
    except Exception as exc:
        LOGGER.exception(
            "ALL_ACCOUNT_BROKER_IDENTITY_V374_%s_FAILED marker=%s error=%s:%s "
            "new_entries_fail_closed=true existing_exits_preserved=true",
            label,
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _install_v289() -> bool:
    return _install_module("bot.runtime_account_scoped_position_state_v289_patch", "V289")


def _install_v377() -> bool:
    return _install_module("bot.runtime_universal_position_materialization_v377_patch", "V377")


def _install_v375() -> bool:
    return _install_module("bot.runtime_universal_sl_tp_policy_v375_patch", "V375")


def _install_v390() -> bool:
    return _install_module("bot.runtime_adaptive_exit_policy_v390_patch", "V390")


def _install_v376() -> bool:
    return _install_module("bot.runtime_universal_four_way_scope_v376_patch", "V376")


def _install_v381() -> bool:
    return _install_module("bot.runtime_kraken_margin_pair_resolution_v381_patch", "V381")


def _install_v379() -> bool:
    return _install_module("bot.runtime_registered_user_protection_proof_v379_patch", "V379")


def _install_v380() -> bool:
    return _install_module("bot.runtime_kraken_native_margin_backup_v380_patch", "V380")


def install_import_hook() -> bool:
    account_scope_ready = _install_v289()
    identity_ready = _patch_v281() if account_scope_ready else False
    materialization_ready = _install_v377() if identity_ready else False

    # v381 starts/reasserts v380 itself. Do this before v375 because native
    # fixed SL/TP backup depends on the already-live Kraken margin stack and
    # pair resolver, not on v375's synchronous all-account policy audit.
    pair_resolution_ready = _install_v381() if materialization_ready else False
    native_backup_installed = bool(pair_resolution_ready)

    # v379 is observational. Starting it early is safe: it remains PENDING
    # until v281 has authoritative four-way rows and never opens/closes trades.
    user_proof_installed = _install_v379() if materialization_ready else False

    LOGGER.critical(
        "ALL_ACCOUNT_BROKER_IDENTITY_V374_AUXILIARY_MONITORS_STARTED marker=%s "
        "kraken_pair_resolution_v381=%s kraken_native_margin_backup_v380=%s "
        "registered_user_proof_v379=%s before_v375_reassert=true "
        "software_margin_protection_remains_authoritative=true forced_trade=false "
        "new_exposure=false safety_gates_bypassed=false",
        MARKER,
        str(pair_resolution_ready).lower(),
        str(native_backup_installed).lower(),
        str(user_proof_installed).lower(),
    )

    policy_ready = _install_v375() if materialization_ready else False
    adaptive_exit_ready = _install_v390() if policy_ready else False
    scope_ready = _install_v376() if adaptive_exit_ready else False

    ready = bool(
        account_scope_ready
        and identity_ready
        and materialization_ready
        and pair_resolution_ready
        and native_backup_installed
        and user_proof_installed
        and policy_ready
        and adaptive_exit_ready
        and scope_ready
    )
    os.environ[_READY_FLAG] = "1" if ready else "0"
    if identity_ready:
        try:
            v281 = importlib.import_module("bot.runtime_all_account_position_exit_coverage_v281_patch")
            audit = getattr(v281, "audit_once", None)
            if callable(audit):
                audit()
        except Exception:
            pass
    LOGGER.critical(
        "RUNTIME_ALL_ACCOUNT_BROKER_IDENTITY_CONVERGENCE_V374_%s marker=%s v416_marker=%s ready=%s "
        "account_scoped_position_v289=%s identity_ready=%s position_materialization_v377=%s "
        "kraken_pair_resolution_v381=%s kraken_native_margin_backup_v380=%s "
        "registered_user_proof_v379=%s universal_four_way_policy_v375=%s "
        "adaptive_exit_policy_v390=%s universal_scope_v376=%s "
        "connected_object_preferred=true current_authoritative_snapshot_preferred=true "
        "newest_snapshot_tiebreak=true snapshot_ttl_unchanged=true "
        "authoritative_stale_cleanup_reasserted=true broker_io_identity_patch=false "
        "manager_registry_mutation=false safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        V416_MARKER,
        str(ready).lower(),
        str(account_scope_ready).lower(),
        str(identity_ready).lower(),
        str(materialization_ready).lower(),
        str(pair_resolution_ready).lower(),
        str(native_backup_installed).lower(),
        str(user_proof_installed).lower(),
        str(policy_ready).lower(),
        str(adaptive_exit_ready).lower(),
        str(scope_ready).lower(),
    )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "V416_MARKER",
    "install",
    "install_import_hook",
    "_score",
    "_candidate_user_brokers",
    "_install_v289",
    "_install_v377",
    "_install_v375",
    "_install_v390",
    "_install_v376",
    "_install_v381",
    "_install_v379",
    "_install_v380",
]
