"""Defer v193 kill-switch transactional recovery until its dependencies exist (v194).

v193 depends on the canonical kill-switch coordinator and v143 provenance chain.
Installing v193 directly from the pre-core v98 umbrella can therefore return false
before those later runtime dependencies are ready, making the entire canonical fast
path fail closed. v194 keeps the pre-core install non-blocking, then installs v193
only after both dependency readiness flags are present.

After v193 is installed, v215 emits bounded causal diagnostics, v216 remains a
best-effort periodic observer, v218 installs the explicit authentication
classifier, and v219 may recover only the exact legacy false-auth signature caused
by the old ``auth`` substring classifier. v220 makes that guarded recovery durable:
it keeps a throttled recovery/diagnostic pulse alive for the lifetime of the
process and registers v194/v220 with the release manifest so installer replay can
self-heal this chain if a startup-only worker ever exits.

Manual/UI/CLI/risk/drawdown/unknown and genuine authentication stops remain
preserved. This patch does not grant execution authority, force LIVE_ACTIVE,
alter nonce/capital/position-sync truth, or change risk/signal thresholds.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time

LOGGER = logging.getLogger("nija.kill_switch_transactional_recovery_v194")
MARKER = "20260823-kill-switch-transactional-recovery-deferred-v194"
DURABLE_MARKER = "20260824-kill-switch-durable-recovery-pulse-v220"
_FLAG = "NIJA_KILL_SWITCH_TRANSACTIONAL_RECOVERY_V194_READY"
_DURABLE_FLAG = "NIJA_KILL_SWITCH_DURABLE_RECOVERY_PULSE_V220_READY"
_LOCK = threading.RLock()
_STARTED = False
_PULSE_STARTED = False


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _dependencies_ready() -> bool:
    return bool(
        _truthy("NIJA_KILL_SWITCH_COORDINATOR_SYNC_READY")
        and _truthy("NIJA_KILL_SWITCH_PERSISTENCE_PROVENANCE_V143_READY")
    )


def _pulse_interval_s() -> float:
    raw = str(os.environ.get("NIJA_KILL_SWITCH_DURABLE_RECOVERY_INTERVAL_S", "30") or "30").strip()
    try:
        return min(300.0, max(15.0, float(raw)))
    except (TypeError, ValueError):
        return 30.0


def _install_v193_once() -> bool:
    module = importlib.import_module("bot.kill_switch_transactional_recovery_v193_patch")
    installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
    if not callable(installer):
        return False
    return installer() is not False


def _install_optional(module_name: str, log_name: str) -> bool:
    try:
        module = importlib.import_module(module_name)
        installer = getattr(module, "install_import_hook", None) or getattr(module, "install", None)
        return callable(installer) and installer() is not False
    except Exception as exc:
        LOGGER.warning(
            "%s_INSTALL_DEFERRED marker=%s err=%s:%s "
            "recovery_eligibility_unchanged=true trading_fail_closed=true",
            log_name,
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _install_v215_diagnostic() -> bool:
    return _install_optional(
        "bot.kill_switch_causal_diagnostic_v215_patch",
        "KILL_SWITCH_CAUSAL_V215",
    )


def _install_v216_diagnostic() -> bool:
    return _install_optional(
        "bot.kill_switch_causal_diagnostic_v216_periodic_patch",
        "KILL_SWITCH_CAUSAL_V216",
    )


def _install_v218_classifier() -> bool:
    return _install_optional(
        "bot.failure_mode_auth_classification_v218_patch",
        "FAILURE_MODE_AUTH_V218",
    )


def _install_v219_recovery() -> bool:
    return _install_optional(
        "bot.kill_switch_false_auth_recovery_v219_patch",
        "KILL_SWITCH_FALSE_AUTH_V219",
    )


def _patch_release_manifest() -> bool:
    """Make the durable recovery owner auditable and replayable.

    v194 was previously only reached indirectly through v98, which allowed the
    release manifest to remain green even if the deferred worker or v216 thread
    stopped making progress.  Registering v194/v220 directly makes installer
    replay re-arm the guarded recovery pulse without changing recovery policy.
    """
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        installers = getattr(manifest, "_INSTALLERS", None)
        if not isinstance(required, dict) or not isinstance(installers, tuple):
            return False
        required["kill_switch_transactional_recovery_v194"] = _FLAG
        required["kill_switch_durable_recovery_pulse_v220"] = _DURABLE_FLAG
        own = ("bot.kill_switch_transactional_recovery_v194_deferred_patch", "install_import_hook")
        if own not in installers:
            manifest._INSTALLERS = tuple(installers) + (own,)
        return True
    except Exception as exc:
        LOGGER.warning(
            "KILL_SWITCH_DURABLE_V220_MANIFEST_DEFERRED marker=%s err=%s:%s "
            "trading_fail_closed=true",
            DURABLE_MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _kill_switch_active() -> bool:
    try:
        module = importlib.import_module("bot.kill_switch")
        getter = getattr(module, "get_kill_switch", None)
        ks = getter() if callable(getter) else None
        status = ks.get_status() if ks is not None and callable(getattr(ks, "get_status", None)) else {}
        return bool(status.get("is_active")) if isinstance(status, dict) else False
    except Exception:
        return False


def _emit_v215_force() -> bool:
    """Force one read-only causal record even when the signature is unchanged."""
    try:
        v215 = importlib.import_module("bot.kill_switch_causal_diagnostic_v215_patch")
        emit = getattr(v215, "emit", None)
        if not callable(emit):
            return False
        lock = getattr(v215, "_LOCK", None)
        if lock is not None:
            with lock:
                setattr(v215, "_LAST_SIGNATURE", "")
        else:
            setattr(v215, "_LAST_SIGNATURE", "")
        return emit() is not False
    except Exception as exc:
        LOGGER.warning(
            "KILL_SWITCH_DURABLE_V220_DIAGNOSTIC_FAILED marker=%s err=%s:%s "
            "state_mutated=false trading_fail_closed=true",
            DURABLE_MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _attempt_v219_once() -> bool:
    """Delegate one attempt to v219's exact-signature guarded recovery policy."""
    try:
        module = importlib.import_module("bot.kill_switch_false_auth_recovery_v219_patch")
        attempt = getattr(module, "attempt_once", None)
        return bool(attempt()) if callable(attempt) else False
    except Exception as exc:
        LOGGER.warning(
            "KILL_SWITCH_DURABLE_V220_RECOVERY_ERROR marker=%s err=%s:%s "
            "active_preserved=true trading_fail_closed=true",
            DURABLE_MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _pulse_once() -> bool:
    """Run one durable, bounded recovery/diagnostic pulse.

    The pulse never decides eligibility itself.  It installs the explicit v218
    classifier, ensures v219 is present, emits v215 causal evidence, and delegates
    the only possible deactivation to v219's exact legacy false-auth policy.
    """
    active_before = _kill_switch_active()
    classifier_ready = _install_v218_classifier()
    recovery_ready = _install_v219_recovery() if classifier_ready else False
    diagnostic_emitted = _emit_v215_force() if active_before else False
    recovered = bool(
        active_before
        and classifier_ready
        and recovery_ready
        and _attempt_v219_once()
    )
    active_after = _kill_switch_active()
    LOGGER.critical(
        "KILL_SWITCH_DURABLE_RECOVERY_V220_PULSE marker=%s active_before=%s "
        "active_after=%s v218_ready=%s v219_ready=%s diagnostic_emitted=%s "
        "recovered=%s exact_legacy_signature_only=true manual_ui_cli_risk_unknown_preserved=true "
        "authority_nonce_execution_not_fabricated=true forced_activation=false "
        "safety_gates_bypassed=false",
        DURABLE_MARKER,
        str(active_before).lower(),
        str(active_after).lower(),
        str(classifier_ready).lower(),
        str(recovery_ready).lower(),
        str(diagnostic_emitted).lower(),
        str(recovered).lower(),
    )
    return recovered


def _pulse_worker() -> None:
    os.environ[_DURABLE_FLAG] = "1"
    LOGGER.critical(
        "KILL_SWITCH_DURABLE_RECOVERY_V220_READY marker=%s ready=true interval_s=%.1f "
        "runtime_lifetime_watch=true release_replay_owner=true exact_false_auth_only=true "
        "manual_ui_cli_risk_unknown_preserved=true execution_authority_unchanged=true "
        "forced_activation=false safety_gates_bypassed=false",
        DURABLE_MARKER,
        _pulse_interval_s(),
    )
    while True:
        try:
            if _dependencies_ready() and _truthy("NIJA_KILL_SWITCH_TRANSACTIONAL_RECOVERY_V193_READY"):
                _pulse_once()
        except Exception as exc:
            LOGGER.warning(
                "KILL_SWITCH_DURABLE_V220_PULSE_ERROR marker=%s err=%s:%s "
                "active_preserved=true trading_fail_closed=true",
                DURABLE_MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(_pulse_interval_s())


def _start_pulse_worker() -> None:
    global _PULSE_STARTED
    with _LOCK:
        if _PULSE_STARTED:
            return
        _PULSE_STARTED = True
        os.environ[_DURABLE_FLAG] = "1"
        threading.Thread(
            target=_pulse_worker,
            name="KillSwitchDurableRecoveryV220",
            daemon=True,
        ).start()


def _publish_ready() -> None:
    os.environ[_FLAG] = "1"
    diagnostic_ready = _install_v215_diagnostic()
    periodic_ready = _install_v216_diagnostic()
    classifier_ready = _install_v218_classifier()
    false_auth_ready = _install_v219_recovery() if classifier_ready else False
    manifest_ready = _patch_release_manifest()
    _start_pulse_worker()
    LOGGER.critical(
        "KILL_SWITCH_TRANSACTIONAL_RECOVERY_V194_READY marker=%s "
        "v193_installed_after_dependencies=true v215_diagnostic_ready=%s "
        "v216_periodic_diagnostic_ready=%s v218_auth_classifier_ready=%s "
        "v219_false_auth_recovery_ready=%s v220_durable_pulse_ready=true "
        "release_manifest_registered=%s pre_core_blocking=false "
        "execution_authority_unchanged=true forced_activation=false "
        "safety_gates_bypassed=false",
        MARKER,
        str(diagnostic_ready).lower(),
        str(periodic_ready).lower(),
        str(classifier_ready).lower(),
        str(false_auth_ready).lower(),
        str(manifest_ready).lower(),
    )


def _worker() -> None:
    while True:
        if _dependencies_ready():
            try:
                if _install_v193_once():
                    _publish_ready()
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
            _install_v215_diagnostic()
            _install_v216_diagnostic()
            classifier_ready = _install_v218_classifier()
            if classifier_ready:
                _install_v219_recovery()
            _patch_release_manifest()
            _start_pulse_worker()
            return True
        if _dependencies_ready():
            try:
                if _install_v193_once():
                    _publish_ready()
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
                "v215_diagnostic_deferred=true v216_periodic_diagnostic_deferred=true "
                "v218_auth_classifier_deferred=true v219_false_auth_recovery_deferred=true "
                "v220_durable_pulse_deferred=true execution_authority_unchanged=true "
                "safety_gates_bypassed=false",
                MARKER,
            )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "DURABLE_MARKER",
    "install",
    "install_import_hook",
    "_pulse_once",
    "_pulse_interval_s",
]
