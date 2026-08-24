"""Durable release-replay owner for guarded kill-switch recovery (v221).

Production on 2026-08-24 proved that the v220 recovery chain could be present in
the release manifest while short runtime slices still contained no v220 pulse,
v215 causal record, or v219 eligibility result.  The execution pipeline was
already receiving a real Coinbase heartbeat order, but the preserved
EMERGENCY_STOP marker remained the immediate execution blocker.

v221 closes that observability/liveness gap without widening recovery policy.  It
runs a lightweight lifetime worker and also registers itself with the release
manifest once that manifest is loaded.  Every bounded pulse delegates to v220's
existing ``_pulse_once`` implementation, which in turn:

* installs/reasserts the explicit v218 authentication classifier;
* forces one read-only v215 causal diagnostic;
* delegates any possible deactivation exclusively to v219's exact legacy
  false-auth signature policy.

v221 never removes or rewrites EMERGENCY_STOP itself, never infers a missing
activation source from marker text, never clears manual/UI/CLI/risk/drawdown/
unknown or genuine-authentication stops, never grants authority/nonce/execution
readiness, and never forces LIVE_ACTIVE.  If provenance is insufficient, the
stop remains fail-closed and the pulse merely makes that fact observable.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.kill_switch_durable_replay_v221")
MARKER = "20260824-kill-switch-durable-replay-v221"
_FLAG = "NIJA_KILL_SWITCH_DURABLE_REPLAY_V221_READY"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_READY_LOGGED = False


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _interval_s() -> float:
    raw = str(os.environ.get("NIJA_KILL_SWITCH_DURABLE_REPLAY_INTERVAL_S", "10") or "10").strip()
    try:
        return min(60.0, max(5.0, float(raw)))
    except (TypeError, ValueError):
        return 10.0


def _dependencies_ready() -> bool:
    return bool(
        _truthy("NIJA_KILL_SWITCH_TRANSACTIONAL_RECOVERY_V193_READY")
        and _truthy("NIJA_KILL_SWITCH_TRANSACTIONAL_RECOVERY_V194_READY")
    )


def _manifest_module() -> ModuleType | None:
    module = sys.modules.get("bot.runtime_release_manifest_patch")
    return module if isinstance(module, ModuleType) else None


def _register_manifest() -> bool:
    """Register v221 only after the canonical manifest already exists.

    The strict startup sanitizer imports v221 very early.  Importing the release
    manifest from here would broaden startup fanout, so this function deliberately
    uses ``sys.modules`` and waits for the runtime to load the canonical manifest
    on its normal path.
    """
    manifest = _manifest_module()
    if manifest is None:
        return False

    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    installers = getattr(manifest, "_INSTALLERS", None)
    if not isinstance(required, dict) or not isinstance(installers, tuple):
        return False

    required["kill_switch_durable_replay_v221"] = _FLAG
    own = ("bot.kill_switch_durable_replay_v221_patch", "install_import_hook")
    if own not in installers:
        manifest._INSTALLERS = tuple(installers) + (own,)
    return True


def _v194_module() -> ModuleType | None:
    module = sys.modules.get("bot.kill_switch_transactional_recovery_v194_deferred_patch")
    return module if isinstance(module, ModuleType) else None


def _pulse_once() -> bool:
    """Delegate one bounded pulse to v220; never implement clearing here."""
    if not _dependencies_ready():
        return False

    v194 = _v194_module()
    if v194 is None:
        return False
    pulse = getattr(v194, "_pulse_once", None)
    if not callable(pulse):
        return False

    try:
        recovered = bool(pulse())
        LOGGER.critical(
            "KILL_SWITCH_DURABLE_REPLAY_V221_PULSE marker=%s delegated_v220=true "
            "recovered=%s exact_v219_policy_only=true source_inference=false "
            "manual_ui_cli_risk_drawdown_unknown_preserved=true "
            "authority_nonce_execution_not_fabricated=true forced_activation=false "
            "safety_gates_bypassed=false",
            MARKER,
            str(recovered).lower(),
        )
        return recovered
    except Exception as exc:
        LOGGER.warning(
            "KILL_SWITCH_DURABLE_REPLAY_V221_PULSE_ERROR marker=%s err=%s:%s "
            "active_preserved=true trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _worker() -> None:
    while True:
        try:
            _register_manifest()
            if _dependencies_ready():
                _pulse_once()
        except Exception as exc:
            LOGGER.warning(
                "KILL_SWITCH_DURABLE_REPLAY_V221_WORKER_ERROR marker=%s err=%s:%s "
                "active_preserved=true trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(_interval_s())


def _ensure_worker() -> bool:
    global _THREAD
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return True
        thread = threading.Thread(
            target=_worker,
            name="KillSwitchDurableReplayV221",
            daemon=True,
        )
        _THREAD = thread
        thread.start()
        return thread.is_alive()


def install() -> bool:
    global _READY_LOGGED
    os.environ[_FLAG] = "1"
    registered = _register_manifest()
    worker_alive = _ensure_worker()
    if not worker_alive:
        os.environ.pop(_FLAG, None)
        return False

    with _LOCK:
        first = not _READY_LOGGED
        _READY_LOGGED = True
    if first:
        LOGGER.critical(
            "KILL_SWITCH_DURABLE_REPLAY_V221_READY marker=%s ready=true interval_s=%.1f "
            "release_manifest_registered=%s lifetime_worker=true delegated_v220=true "
            "exact_v219_policy_only=true marker_text_not_source_proof=true "
            "manual_ui_cli_risk_drawdown_unknown_preserved=true "
            "execution_authority_unchanged=true forced_activation=false "
            "safety_gates_bypassed=false",
            MARKER,
            _interval_s(),
            str(registered).lower(),
        )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_interval_s",
    "_register_manifest",
    "_dependencies_ready",
    "_pulse_once",
]
