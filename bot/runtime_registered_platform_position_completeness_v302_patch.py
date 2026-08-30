"""Registered platform position completeness fence v302.

Production generation 5019 on 2026-08-30 exposed a fail-open denominator bug in
the position-readiness certificate.  v95 builds ``position_sync_status`` from
connected brokers only and v294 correctly isolates that status to platform
accounts.  If a registered platform broker disconnects, however, its row can
vanish from the status map entirely.  v96 then sees a non-empty all-true map for
the remaining venues and may publish ``position_sync_ready=true`` even though the
registered platform denominator is incomplete.

v302 makes registered platform membership authoritative for the canonical
position-readiness denominator.  Every non-null broker in the manager's platform
registry receives an explicit ``platform:<venue>`` row.  A row can be true only
when the registered broker is genuinely connected *and* the already-wrapped
v95/v294 position status reports that exact row true.  Disconnected registered
brokers and connected brokers missing position proof remain explicit false rows.
User-account rows remain outside the canonical platform activation certificate;
v282/v281/v285 continue to enforce their independent entry and exit coverage.

No broker is connected, disconnected, registered, removed, or otherwise mutated
by this patch.  No position snapshot, cost basis, balance, freshness timestamp,
capital publication, writer/nonce authority, execution proof, order, fill, or
risk state is fabricated or extended.  The change only closes an incomplete
readiness denominator and therefore fails closed when registered platform truth
is missing.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from collections.abc import Mapping
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_registered_platform_position_completeness_v302")
MARKER = "20260830-registered-platform-position-completeness-v302"
RELEASE_ID = "20260830-runtime-convergence-v302"
_READY_FLAG = "NIJA_RUNTIME_REGISTERED_PLATFORM_POSITION_COMPLETENESS_V302_READY"
_PATCH_ATTR = "_nija_registered_platform_position_completeness_v302"
_LOCK = threading.RLock()
_LAST_SIGNATURE = ""


def _v95() -> Any:
    return importlib.import_module("bot.position_sync_core_handoff_v95_patch")


def _label(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _connected(broker: Any) -> bool:
    if broker is None:
        return False
    try:
        value = getattr(broker, "connected", False)
        return bool(value() if callable(value) else value)
    except Exception:
        return False


def _registered_platform_brokers(manager: Any) -> dict[str, Any]:
    """Return the canonical registered platform denominator without mutation."""
    if manager is None:
        return {}

    mapping: Any = getattr(manager, "_platform_brokers", None)
    if not isinstance(mapping, Mapping):
        mapping = getattr(manager, "platform_brokers", None)
        if callable(mapping):
            try:
                mapping = mapping()
            except Exception:
                mapping = None
    if not isinstance(mapping, Mapping):
        return {}

    registered: dict[str, Any] = {}
    for broker_type, broker in list(mapping.items()):
        if broker is None:
            continue
        name = _label(broker_type)
        if not name:
            continue
        registered[f"platform:{name}"] = broker
    return registered


def _chain_has_patch(callable_obj: Any) -> bool:
    seen: set[int] = set()
    current = callable_obj
    for _ in range(128):
        if not callable(current) or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, _PATCH_ATTR, False)):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _emit_state(
    status: dict[str, bool],
    registered: dict[str, Any],
    raw_status: dict[str, bool],
) -> None:
    global _LAST_SIGNATURE
    pending = tuple(sorted(name for name, ready in status.items() if not ready))
    disconnected = tuple(sorted(name for name, broker in registered.items() if not _connected(broker)))
    missing_proof = tuple(
        sorted(
            name
            for name, broker in registered.items()
            if _connected(broker) and not bool(raw_status.get(name, False))
        )
    )
    signature = repr((tuple(sorted(status.items())), disconnected, missing_proof))
    with _LOCK:
        if signature == _LAST_SIGNATURE:
            return
        _LAST_SIGNATURE = signature

    ready = bool(status) and not pending
    log = LOGGER.info if ready else LOGGER.critical
    log(
        "REGISTERED_PLATFORM_POSITION_V302_STATE marker=%s ready=%s registered=%d connected=%d "
        "status=%s pending=%s disconnected=%s missing_position_proof=%s "
        "registered_denominator_preserved=true user_rows_excluded_from_platform_activation=true "
        "broker_connectivity_mutated=false position_success_fabricated=false freshness_extended=false "
        "execution_proof_fabricated=false forced_activation=false "
        "writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
        MARKER,
        str(ready).lower(),
        len(status),
        sum(1 for broker in registered.values() if _connected(broker)),
        status,
        pending,
        disconnected,
        missing_proof,
    )


def _patch_v95_status() -> bool:
    try:
        v95 = _v95()
    except Exception:
        return False
    current = getattr(v95, "position_sync_status", None)
    if not callable(current):
        return False
    if _chain_has_patch(current):
        return True
    original = current

    @wraps(original)
    def position_sync_status_v302(manager: Any) -> tuple[bool, list[str], dict[str, bool]]:
        _raw_ready, _raw_pending, raw = original(manager)
        raw_status = dict(raw or {}) if isinstance(raw, Mapping) else {}
        # Preserve v294's platform/user isolation even if an earlier wrapper
        # returns user rows: only registered platform rows enter this certificate.
        registered = _registered_platform_brokers(manager)
        status = {
            name: bool(_connected(broker) and raw_status.get(name, False))
            for name, broker in sorted(registered.items())
        }
        pending = sorted(name for name, ready in status.items() if not ready)
        ready = bool(status) and not pending
        _emit_state(status, registered, raw_status)
        return ready, pending, status

    position_sync_status_v302.__name__ = "position_sync_status_v302"
    setattr(position_sync_status_v302, _PATCH_ATTR, True)
    setattr(position_sync_status_v302, "__wrapped__", original)
    v95.position_sync_status = position_sync_status_v302
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_registered_platform_position_completeness_v302"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, Any]:
    patched = _patch_v95_status()
    return {
        "ready": bool(patched),
        "registered_platform_position_denominator": bool(patched),
    }


def install() -> bool:
    manifest_ok = _register_manifest()
    patched = _patch_v95_status()
    ready = bool(manifest_ok and patched)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_REGISTERED_PLATFORM_POSITION_COMPLETENESS_V302_%s marker=%s ready=%s "
        "registered_platform_denominator_required=true disconnected_registered_explicit_false=true "
        "connected_missing_proof_explicit_false=true user_execution_isolation_preserved=true "
        "position_success_fabricated=false connectivity_fabricated=false freshness_extended=false "
        "execution_proof_fabricated=false forced_trade=false forced_activation=false "
        "writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "reconcile_once",
    "_label",
    "_connected",
    "_registered_platform_brokers",
    "_patch_v95_status",
]
