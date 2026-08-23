"""Defer v193 kill-switch transactional recovery until its dependencies exist (v194).

v193 depends on the canonical kill-switch coordinator and v143 provenance chain.
Installing v193 directly from the pre-core v98 umbrella can therefore return false
before those later runtime dependencies are ready, making the entire canonical fast
path fail closed. v194 keeps the pre-core install non-blocking, then installs v193
only after both dependency readiness flags are present.

This patch changes install ordering only. It does not clear the kill switch, grant
execution authority, force LIVE_ACTIVE, alter nonce/capital/position-sync truth, or
change risk/signal thresholds.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time

LOGGER = logging.getLogger("nija.kill_switch_transactional_recovery_v194")
MARKER = "20260823-kill-switch-transactional-recovery-deferred-v194"
_FLAG = "NIJA_KILL_SWITCH_TRANSACTIONAL_RECOVERY_V194_READY"
_LOCK = threading.RLock()
_STARTED = False


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _dependencies_ready() -> bool:
    return bool(
        _truthy("NIJA_KILL_SWITCH_COORDINATOR_SYNC_READY")
        and _truthy("NIJA_KILL_SWITCH_PERSISTENCE_PROVENANCE_V143_READY")
    )


def _install_v193_once() -> bool:
    module = importlib.import_module("bot.kill_switch_transactional_recovery_v193_patch")
    installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer):
        return False
    return installer() is not False


def _worker() -> None:
    while True:
        if _dependencies_ready():
            try:
                if _install_v193_once():
                    os.environ[_FLAG] = "1"
                    LOGGER.critical(
                        "KILL_SWITCH_TRANSACTIONAL_RECOVERY_V194_READY marker=%s "
                        "v193_installed_after_dependencies=true pre_core_blocking=false "
                        "execution_authority_unchanged=true forced_activation=false "
                        "safety_gates_bypassed=false",
                        MARKER,
                    )
                    return
            except Exception as exc:
                LOGGER.warning(
                    "KILL_SWITCH_TRANSACTIONAL_RECOVERY_V194_RETRY marker=%s "
                    "err=%s:%s trading_fail_closed=true",
                    MARKER,
                    type(exc).__name__,
                    exc,
                )
        time.sleep(1.0)


def install() -> bool:
    global _STARTED
    with _LOCK:
        if _truthy(_FLAG):
            return True
        if _dependencies_ready():
            try:
                if _install_v193_once():
                    os.environ[_FLAG] = "1"
                    LOGGER.critical(
                        "KILL_SWITCH_TRANSACTIONAL_RECOVERY_V194_READY marker=%s "
                        "v193_installed_after_dependencies=true pre_core_blocking=false "
                        "execution_authority_unchanged=true forced_activation=false "
                        "safety_gates_bypassed=false",
                        MARKER,
                    )
                    return True
            except Exception as exc:
                LOGGER.warning(
                    "KILL_SWITCH_TRANSACTIONAL_RECOVERY_V194_INITIAL_DEFER marker=%s "
                    "err=%s:%s trading_fail_closed=true",
                    MARKER,
                    type(exc).__name__,
                    exc,
                )
        if not _STARTED:
            _STARTED = True
            thread = threading.Thread(
                target=_worker,
                name="KillSwitchTransactionalRecoveryV194",
                daemon=True,
            )
            thread.start()
            LOGGER.critical(
                "KILL_SWITCH_TRANSACTIONAL_RECOVERY_V194_ARMED marker=%s "
                "dependency_wait=true pre_core_blocking=false v193_not_skipped=true "
                "execution_authority_unchanged=true safety_gates_bypassed=false",
                MARKER,
            )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook"]
