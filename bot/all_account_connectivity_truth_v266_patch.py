"""All-account connectivity truth and recovery liveness v266.

The platform can remain safely LIVE_ACTIVE while an isolated user account is
unavailable.  The remaining production gap was narrower: the canonical live
broker reconciler reported only aggregate user counts and did not explicitly
pulse the already-installed v86/v90 authenticated Kraken-user recovery chain.
That made a persistent 1/2 user snapshot ambiguous even though the recovery
machinery itself was present.

This patch does two things without weakening any safety gate:

* every live-broker reconciliation pass performs one best-effort v86/v90 user
  reconciliation pulse before publishing the connectivity snapshot; and
* v86 reconciliation emits a state-sensitive diagnostic including the existing
  per-account recovery state plus canonical failed/missing-credential counts.

No credentials, connected flags, trading eligibility, balances, writer proof,
nonce state, execution authority, kill-switch state, or platform readiness are
fabricated.  User failures remain isolated and never become a reason to force
or revoke global LIVE_ACTIVE by this patch.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

from bot import kraken_all_account_supervision_v86 as v86


LOGGER = logging.getLogger("nija.all_account_connectivity_truth_v266")
MARKER = "20260828-all-account-connectivity-truth-v266"
_LOCK = threading.RLock()
_INSTALLED = False
_MONITOR_STARTED = False
_ORIGINAL_V86_RECONCILE = None
_PATCHED_V25_IDS: set[int] = set()
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
        "user_failures=%s user_without_credentials=%s authenticated_only=true "
        "fabricated_connected=false fabricated_credentials=false "
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
        state = original(manager)
        observed_manager = manager if manager is not None else _canonical_manager()
        if isinstance(state, dict):
            _emit_state(observed_manager, state, source="v86_reconcile")
        return state

    setattr(_reconcile_once, "_nija_v266_connectivity_truth", True)
    setattr(_reconcile_once, "_nija_v266_original", original)
    v86.reconcile_once = _reconcile_once
    return True


def _pulse_user_recovery(manager: Any) -> dict[str, Any]:
    """Run one existing v86/v90 recovery pass; never synthesize readiness."""
    try:
        state = v86.reconcile_once(manager)
    except Exception as exc:
        LOGGER.warning(
            "ALL_ACCOUNT_CONNECTIVITY_V266_PULSE_FAILED marker=%s error=%s:%s "
            "isolated=true platform_live_state_unchanged=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return {"ok": False, "reason": f"reconcile_error:{type(exc).__name__}", "states": {}}
    return state if isinstance(state, dict) else {"ok": False, "reason": "invalid_reconcile_state", "states": {}}


def _patch_live_broker_reconciler(module: ModuleType) -> bool:
    module_id = id(module)
    with _LOCK:
        if module_id in _PATCHED_V25_IDS:
            return True
    original = getattr(module, "_reconcile_brokers_once", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_v266_user_recovery_pulse", False):
        with _LOCK:
            _PATCHED_V25_IDS.add(module_id)
        return True

    def _reconcile_brokers_once() -> dict[str, bool]:
        manager_getter = getattr(module, "_manager", None)
        manager = manager_getter() if callable(manager_getter) else _canonical_manager()
        state = _pulse_user_recovery(manager)
        _emit_state(manager, state, source="live_broker_reconcile")
        # Preserve v25 as the sole owner of platform connectivity publication,
        # broker registration, and exit-supervisor reconciliation.
        return original()

    setattr(_reconcile_brokers_once, "_nija_v266_user_recovery_pulse", True)
    setattr(_reconcile_brokers_once, "_nija_v266_original", original)
    module._reconcile_brokers_once = _reconcile_brokers_once
    with _LOCK:
        _PATCHED_V25_IDS.add(module_id)
    LOGGER.critical(
        "ALL_ACCOUNT_CONNECTIVITY_V266_V25_PATCHED marker=%s module=%s "
        "authenticated_recovery_pulse=true platform_connectivity_return_unchanged=true "
        "user_failure_isolated=true safety_gates_bypassed=false",
        MARKER,
        getattr(module, "__name__", "unknown"),
    )
    return True


def _try_patch_v25_loaded() -> bool:
    patched = False
    for name in ("bot.live_broker_profit_exit_convergence_v25", "live_broker_profit_exit_convergence_v25"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_live_broker_reconciler(module) or patched
    return patched


def _monitor() -> None:
    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        _patch_v86_reconcile()
        if _try_patch_v25_loaded():
            return
        time.sleep(0.25)
    LOGGER.warning(
        "ALL_ACCOUNT_CONNECTIVITY_V266_MONITOR_EXPIRED marker=%s v86_patched=%s "
        "platform_live_state_unchanged=true",
        MARKER,
        bool(getattr(getattr(v86, "reconcile_once", None), "_nija_v266_connectivity_truth", False)),
    )


def install_import_hook() -> bool:
    global _INSTALLED, _MONITOR_STARTED
    _patch_v86_reconcile()
    _try_patch_v25_loaded()
    with _LOCK:
        if not _MONITOR_STARTED:
            _MONITOR_STARTED = True
            threading.Thread(
                target=_monitor,
                name="AllAccountConnectivityTruthV266",
                daemon=True,
            ).start()
        _INSTALLED = True
    os.environ["NIJA_ALL_ACCOUNT_CONNECTIVITY_TRUTH_V266_INSTALLED"] = "1"
    LOGGER.critical(
        "ALL_ACCOUNT_CONNECTIVITY_TRUTH_V266_READY marker=%s ready=true "
        "v86_state_sensitive_diagnostics=true v90_recovery_path_preserved=true "
        "live_broker_recovery_pulse=true credentials_fabricated=false "
        "connected_fabricated=false trading_eligibility_fabricated=false "
        "platform_live_state_unchanged=true kill_switch_unchanged=true "
        "writer_nonce_risk_capital_order_fill_gates_unchanged=true safety_gates_bypassed=false",
        MARKER,
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_pulse_user_recovery",
    "_patch_live_broker_reconciler",
    "_patch_v86_reconcile",
]
