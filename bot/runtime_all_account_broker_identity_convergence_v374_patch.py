"""Converge all-account coverage onto the current canonical broker object v374.

v90 may rebuild a Kraken user broker after startup. During that handoff the
canonical manager can briefly contain both the retired broker object and the
new authenticated broker in different compatibility registries. v281 builds
its denominator from all of those registries, and a later stale registry entry
can overwrite the current connected object for the same account key. The
result is a false ``disconnected`` coverage blocker even while v86/v90 have
already authenticated the replacement broker.

v374 changes only broker-object selection for duplicate account keys. It keeps
v281's complete enabled-account denominator, performs no broker I/O, does not
mutate manager registries, and never fabricates connectivity, position proof,
protection, capital, nonce, writer authority, fills, or execution readiness.
For duplicate user-account objects it prefers the object with the strongest
already-existing local truth: connected, startup fetch proof, startup adoption,
and a current v285 snapshot timestamp. Platform identities are unchanged.

v375 is chained after identity convergence so universal fixed/trailing SL/TP
policy is required for platform and registered-user exits. v376 is chained
after v375 so every currently connected canonical broker, including future
broker/user registrations, must expose the universal position/price/close
interfaces before new exposure can execute.
"""
from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_all_account_broker_identity_convergence_v374")
MARKER = "20260905-all-account-broker-identity-convergence-v374"
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


def _score(broker: Any) -> tuple[int, int, int, int]:
    if broker is None:
        return (0, 0, 0, 0)
    connected = 1 if _connected(broker) else 0
    fetch = 1 if getattr(broker, "_startup_position_sync_fetch_ok", None) is True else 0
    adopted = 1 if getattr(broker, "_startup_position_sync_adopted", None) is True else 0
    current_snapshot = 0
    try:
        at = float(getattr(broker, "_nija_authoritative_position_snapshot_at_monotonic_v285", 0.0) or 0.0)
        current_snapshot = 1 if at > 0 else 0
    except Exception:
        current_snapshot = 0
    return (connected, fetch, adopted, current_snapshot)


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
        replacements: list[tuple[str, tuple[int, int, int, int], tuple[int, int, int, int]]] = []
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
                "ALL_ACCOUNT_BROKER_IDENTITY_V374_RECONCILED marker=%s replacements=%s "
                "broker_io=false registry_mutation=false connectivity_fabricated=false "
                "position_proof_fabricated=false protection_fabricated=false",
                MARKER,
                replacements,
            )
        return expected

    setattr(expected_accounts_v374, _PATCH_ATTR, True)
    setattr(expected_accounts_v374, "__wrapped__", current)
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


def _install_v375() -> bool:
    return _install_module("bot.runtime_universal_sl_tp_policy_v375_patch", "V375")


def _install_v376() -> bool:
    return _install_module("bot.runtime_universal_four_way_scope_v376_patch", "V376")


def install_import_hook() -> bool:
    identity_ready = _patch_v281()
    policy_ready = _install_v375() if identity_ready else False
    scope_ready = _install_v376() if policy_ready else False
    ready = bool(identity_ready and policy_ready and scope_ready)
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
        "RUNTIME_ALL_ACCOUNT_BROKER_IDENTITY_CONVERGENCE_V374_%s marker=%s ready=%s "
        "identity_ready=%s universal_four_way_policy_v375=%s universal_scope_v376=%s "
        "connected_object_preferred=true startup_fetch_proof_preferred=true "
        "startup_adoption_preferred=true broker_io=false manager_registry_mutation=false "
        "safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
        str(identity_ready).lower(),
        str(policy_ready).lower(),
        str(scope_ready).lower(),
    )
    return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_score",
    "_candidate_user_brokers",
    "_install_v375",
    "_install_v376",
]
