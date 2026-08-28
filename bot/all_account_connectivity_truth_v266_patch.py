"""All-account connectivity truth v266.

NIJA may remain safely LIVE_ACTIVE while an isolated user account is
unavailable. The production gap addressed here is observability: v86/v90
already own authenticated Kraken-user rebuild/reconnect behavior, but a stable
1/2 aggregate connectivity snapshot does not reveal whether the unavailable
account is in backoff, missing credentials, unavailable, or reconnecting.

This patch wraps the existing v86 reconciliation call only to emit a
state-sensitive diagnostic containing the existing per-account recovery state
and canonical failed/missing-credential counts. It does not add another
reconciliation call, reconnect attempt, broker I/O path, or retry cadence.

No credentials, connected flags, trading eligibility, balances, writer proof,
nonce state, execution authority, kill-switch state, platform readiness, order,
or fill state are fabricated or changed.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Any

from bot import kraken_all_account_supervision_v86 as v86


LOGGER = logging.getLogger("nija.all_account_connectivity_truth_v266")
MARKER = "20260828-all-account-connectivity-truth-v266"
_LOCK = threading.RLock()
_INSTALLED = False
_ORIGINAL_V86_RECONCILE = None
_LAST_STATE_SIGNATURE = ""


def _canonical_manager() -> Any:
    module = sys.modules.get("bot.multi_account_broker_manager")
    getter = getattr(module, "get_broker_manager", None) if module is not None else None
    if callable(getter):
        try:
            return getter()
        except Exception:
            return None
    return getattr(module, "multi_account_broker_manager", None) if module is not None else None


def _registry_counts(manager: Any) -> tuple[int, int]:
    if manager is None:
        return 0, 0
    try:
        from bot.account_registry_snapshot import build_account_registry_snapshot

        snapshot = build_account_registry_snapshot(manager)
        return int(snapshot.user_failures), int(snapshot.user_without_credentials)
    except Exception:
        return (
            len(getattr(manager, "_failed_user_connections", {}) or {}),
            len(getattr(manager, "_users_without_credentials", {}) or {}),
        )


def _state_signature(state: dict[str, Any], failed: int, missing: int) -> str:
    states = state.get("states", {}) if isinstance(state, dict) else {}
    try:
        ordered = tuple(sorted((str(k), str(v)) for k, v in states.items()))
    except Exception:
        ordered = ()
    return repr((
        state.get("registered", 0) if isinstance(state, dict) else 0,
        state.get("connected", 0) if isinstance(state, dict) else 0,
        state.get("disconnected", 0) if isinstance(state, dict) else 0,
        state.get("reason", "unknown") if isinstance(state, dict) else "invalid_state",
        failed,
        missing,
        ordered,
    ))


def _emit_state(manager: Any, state: dict[str, Any], *, source: str) -> None:
    global _LAST_STATE_SIGNATURE
    failed, missing = _registry_counts(manager)
    signature = _state_signature(state, failed, missing)
    with _LOCK:
        if signature == _LAST_STATE_SIGNATURE:
            return
        _LAST_STATE_SIGNATURE = signature
    states = state.get("states", {}) if isinstance(state, dict) else {}
    ready = bool(state.get("ok")) if isinstance(state, dict) else False
    log = LOGGER.critical if ready else LOGGER.warning
    log(
        "ALL_ACCOUNT_CONNECTIVITY_V266_STATE marker=%s source=%s registered=%s "
        "connected=%s disconnected=%s recovery_reason=%s states=%s "
        "user_failures=%s user_without_credentials=%s authenticated_recovery_owner=v86_v90 "
        "extra_broker_io=false retry_cadence_unchanged=true fabricated_connected=false "
        "fabricated_credentials=false trading_eligibility_unchanged=true "
        "platform_live_state_unchanged=true user_failure_isolated=true",
        MARKER,
        source,
        state.get("registered", 0) if isinstance(state, dict) else 0,
        state.get("connected", 0) if isinstance(state, dict) else 0,
        state.get("disconnected", 0) if isinstance(state, dict) else 0,
        state.get("reason", "unknown") if isinstance(state, dict) else "invalid_state",
        states,
        failed,
        missing,
    )


def _patch_v86_reconcile() -> bool:
    global _ORIGINAL_V86_RECONCILE
    current = getattr(v86, "reconcile_once", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_v266_connectivity_truth", False):
        return True

    original = current
    _ORIGINAL_V86_RECONCILE = original

    def _reconcile_once(manager: Any = None) -> dict[str, Any]:
        # Exactly one call to the pre-existing v86/v90 path. v266 observes its
        # result only; it does not add broker I/O or change recovery policy.
        state = original(manager)
        observed_manager = manager if manager is not None else _canonical_manager()
        if isinstance(state, dict):
            _emit_state(observed_manager, state, source="v86_reconcile")
        return state

    setattr(_reconcile_once, "_nija_v266_connectivity_truth", True)
    setattr(_reconcile_once, "_nija_v266_original", original)
    v86.reconcile_once = _reconcile_once
    return True


def install_import_hook() -> bool:
    global _INSTALLED
    patched = _patch_v86_reconcile()
    with _LOCK:
        _INSTALLED = bool(patched)
    if patched:
        os.environ["NIJA_ALL_ACCOUNT_CONNECTIVITY_TRUTH_V266_INSTALLED"] = "1"
    LOGGER.critical(
        "ALL_ACCOUNT_CONNECTIVITY_TRUTH_V266_READY marker=%s ready=%s "
        "v86_state_sensitive_diagnostics=true v90_recovery_path_preserved=true "
        "extra_reconcile_calls=false extra_broker_io=false retry_cadence_unchanged=true "
        "credentials_fabricated=false connected_fabricated=false "
        "trading_eligibility_unchanged=true platform_live_state_unchanged=true "
        "kill_switch_unchanged=true writer_nonce_risk_capital_order_fill_gates_unchanged=true "
        "safety_gates_bypassed=false",
        MARKER,
        str(bool(patched)).lower(),
    )
    return bool(patched)


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_patch_v86_reconcile",
    "_registry_counts",
    "_state_signature",
]
