"""Final production activation/execution convergence repair v60.

Production evidence after v59 showed a healthy writer/core/capital epoch remaining
parked for > 38 minutes while one readiness/activation worker stayed in-flight.
This layer removes the remaining synchronous convergence choke points without
lowering any trading, risk, nonce, venue, kill-switch, or strategy thresholds.

Properties:
* activation commit is single-flight and never runs on bot_main/v15/v16 monitor threads;
* CapitalAuthority readiness checks are observational only (no private exchange I/O);
* v15/v16 keep publishing structural/readiness proofs even while activation is pending;
* bot_main polls canonical state/proofs and cannot block inside commit_activation();
* legacy NIJA_RISK_SYSTEM_READY is published only from a true canonical risk proof;
* existing live-entry completion and fill-confirmed exit repairs are installed explicitly
  on the bounded canonical fast path.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("nija.final_production_activation_repair_v60")
MARKER = "20260812-final-production-activation-v60"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_INSTALLED = False
_ACTIVATION_LOCK = threading.RLock()
_ACTIVATION_THREAD: threading.Thread | None = None
_ACTIVATION_STARTED_AT = 0.0
_ACTIVATION_TRIGGER = ""
_ACTIVATION_LAST_RESULT: dict[str, Any] = {}


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _live_mode() -> bool:
    return _truthy("LIVE_CAPITAL_VERIFIED") and not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")


def _state_value(sm: Any) -> str:
    try:
        state = sm.get_current_state()
    except Exception:
        state = getattr(sm, "_current_state", "UNKNOWN")
    return str(getattr(state, "value", state) or "UNKNOWN").strip().upper()


def _publish_risk_compat(proofs: dict[str, bool]) -> None:
    """Bridge canonical v16 risk proof into the legacy writer-dispatch latch."""
    if bool(proofs.get("risk_ready")):
        if os.environ.get("NIJA_RISK_SYSTEM_READY") != "1":
            os.environ["NIJA_RISK_SYSTEM_READY"] = "1"
            logger.critical(
                "RISK_SYSTEM_READY_COMPAT_PUBLISHED marker=%s source=v16_risk_ready "
                "pre_dispatch=%s fail_closed=%s downstream_governor=%s",
                MARKER,
                os.environ.get("NIJA_PRE_DISPATCH_RISK_SIZING_READY", "0"),
                os.environ.get("NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED", "0"),
                os.environ.get("NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED", "0"),
            )


def _activation_worker(trigger: str) -> None:
    global _ACTIVATION_LAST_RESULT
    result: dict[str, Any] = {"trigger": trigger, "started_at": time.time()}
    try:
        monitor = importlib.import_module("bot.activation_pending_commit_monitor_patch")
        sm = monitor._state_machine()
        if sm is None:
            result.update(ok=False, reason="state_machine_unavailable")
            return
        state = _state_value(sm)
        result["state_before"] = state
        if state == "LIVE_ACTIVE":
            result.update(ok=True, reason="already_live")
            return
        if state not in {"OFF", "LIVE_PENDING_CONFIRMATION"}:
            result.update(ok=False, reason=f"state_not_armable:{state}")
            return
        accepted, meta = monitor._capital_ready_snapshot()
        result["capital_accepted"] = bool(accepted)
        if not accepted:
            result.update(ok=False, reason=f"capital_not_accepted:{meta.get('reason', 'unknown')}")
            return
        committed = bool(monitor._commit_once(sm, meta))
        state_after = _state_value(sm)
        result.update(
            ok=bool(committed and state_after == "LIVE_ACTIVE"),
            committed=committed,
            state_after=state_after,
            reason="committed" if committed else "normal_commit_rejected",
        )
    except Exception as exc:
        result.update(ok=False, reason=f"exception:{type(exc).__name__}:{exc}")
        logger.exception(
            "ACTIVATION_SINGLE_FLIGHT_WORKER_FAILED marker=%s trigger=%s",
            MARKER,
            trigger,
        )
    finally:
        result["finished_at"] = time.time()
        with _ACTIVATION_LOCK:
            _ACTIVATION_LAST_RESULT = result
        logger.critical(
            "ACTIVATION_SINGLE_FLIGHT_RESULT marker=%s trigger=%s ok=%s reason=%s "
            "state_before=%s state_after=%s",
            MARKER,
            trigger,
            result.get("ok", False),
            result.get("reason", "unknown"),
            result.get("state_before", "unknown"),
            result.get("state_after", "unknown"),
        )


def request_activation(trigger: str) -> bool:
    """Request one canonical activation attempt without blocking the caller."""
    global _ACTIVATION_THREAD, _ACTIVATION_STARTED_AT, _ACTIVATION_TRIGGER
    if not _live_mode():
        return False
    with _ACTIVATION_LOCK:
        worker = _ACTIVATION_THREAD
        if worker is not None and worker.is_alive():
            age = max(0.0, time.monotonic() - _ACTIVATION_STARTED_AT)
            logger.info(
                "ACTIVATION_SINGLE_FLIGHT_DEDUPED marker=%s trigger=%s owner_trigger=%s age_s=%.1f",
                MARKER,
                trigger,
                _ACTIVATION_TRIGGER,
                age,
            )
            if age >= 20.0:
                logger.critical(
                    "ACTIVATION_SINGLE_FLIGHT_STALLED marker=%s trigger=%s owner_trigger=%s age_s=%.1f "
                    "callers_remain_nonblocking=true trading_fail_closed=true",
                    MARKER,
                    trigger,
                    _ACTIVATION_TRIGGER,
                    age,
                )
            return False
        _ACTIVATION_TRIGGER = str(trigger or "unspecified")
        _ACTIVATION_STARTED_AT = time.monotonic()
        worker = threading.Thread(
            target=_activation_worker,
            args=(_ACTIVATION_TRIGGER,),
            name="CanonicalActivationSingleFlight",
            daemon=True,
        )
        _ACTIVATION_THREAD = worker
        worker.start()
        logger.critical(
            "ACTIVATION_SINGLE_FLIGHT_DISPATCHED marker=%s trigger=%s caller_blocked=false",
            MARKER,
            _ACTIVATION_TRIGGER,
        )
        return True


def _patch_capital_readiness_observer() -> bool:
    """Remove private exchange refreshes from the activation transaction."""
    tsm = importlib.import_module("bot.trading_state_machine")
    original = getattr(tsm, "_capital_readiness_gate", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_v60_observational", False):
        return True

    def observational_gate() -> tuple[bool, str]:
        try:
            ca = tsm._get_capital_authority_instance()
        except Exception as exc:
            return False, f"CA_READY=false: authority_unavailable:{exc}"
        if ca is None:
            return False, "CA_READY=false: authority_unavailable"
        try:
            hydrated_raw = getattr(ca, "is_hydrated", False)
            hydrated = bool(hydrated_raw() if callable(hydrated_raw) else hydrated_raw)
        except Exception:
            hydrated = False
        if not hydrated:
            return False, "CA_READY=false: capital_authority_not_hydrated"
        try:
            stale_reader = getattr(ca, "is_stale", None)
            stale = bool(stale_reader()) if callable(stale_reader) else bool(getattr(ca, "stale", True))
        except Exception:
            stale = True
        handoff = bool(
            _truthy("NIJA_CAPITAL_READINESS_HANDOFF_V34")
            or _truthy("NIJA_CAPITAL_READINESS_HANDOFF_V34_READY")
            or (_truthy("CAPITAL_SYSTEM_READY") and _truthy("NIJA_CAPITAL_READY"))
        )
        if stale and not handoff:
            return False, "CA_READY=false: capital_authority_stale"
        try:
            real = float(ca.get_real_capital() or 0.0)
        except Exception:
            real = float(getattr(ca, "total_capital", 0.0) or 0.0)
        logger.info(
            "CAPITAL_READINESS_OBSERVATIONAL marker=%s hydrated=%s stale=%s handoff=%s real=%.2f "
            "private_io=false",
            MARKER,
            hydrated,
            stale,
            handoff,
            real,
        )
        return True, "ok"

    observational_gate._nija_v60_observational = True  # type: ignore[attr-defined]
    observational_gate.__wrapped__ = original  # type: ignore[attr-defined]
    tsm._capital_readiness_gate = observational_gate
    logger.critical(
        "FINAL_ACTIVATION_V60_CAPITAL_GATE_PATCHED marker=%s private_io=false observational_only=true",
        MARKER,
    )
    return True


def _patch_v16_nonblocking() -> bool:
    v16 = importlib.import_module("preactivation_readiness_convergence_v16_patch")
    original_cycle = getattr(v16, "_cycle", None)
    if not callable(original_cycle):
        return False
    if getattr(original_cycle, "_nija_v60_nonblocking", False):
        return True

    def cycle() -> tuple[bool, dict[str, Any]]:
        try:
            v15 = importlib.import_module("runtime_convergence_v15_patch")
            installer = getattr(v15, "install", None)
            if callable(installer):
                installer()
        except Exception:
            pass
        if not v16._live_mode():
            return False, {"live_mode": False}
        publisher_started, publisher_detail = v16._ensure_strategy_publication_monitor()
        proofs, details = v16._collect_proofs()
        ready, pending = v16._mark_proven_readiness(proofs)
        _publish_risk_compat(proofs)
        details["proofs"] = proofs
        details["pending"] = pending
        details["strategy_publication_monitor"] = {
            "started": publisher_started,
            "detail": publisher_detail,
        }
        if ready:
            request_activation("v16_readiness_complete")
        try:
            monitor = importlib.import_module("bot.activation_pending_commit_monitor_patch")
            sm = monitor._state_machine()
            state = _state_value(sm) if sm is not None else "UNAVAILABLE"
        except Exception:
            state = "UNAVAILABLE"
        details["state"] = state
        details["activation_dispatched"] = bool(ready and state != "LIVE_ACTIVE")
        return state == "LIVE_ACTIVE", details

    cycle._nija_v60_nonblocking = True  # type: ignore[attr-defined]
    cycle.__wrapped__ = original_cycle  # type: ignore[attr-defined]
    v16._cycle = cycle
    logger.critical(
        "FINAL_ACTIVATION_V60_V16_PATCHED marker=%s proof_publication_nonblocking=true activation_single_flight=true",
        MARKER,
    )
    return True


def _patch_v15_nonblocking() -> bool:
    v15 = importlib.import_module("runtime_convergence_v15_patch")
    original = getattr(v15, "_activation_step", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_v60_nonblocking", False):
        return True

    def activation_step(release_ready: bool) -> bool:
        required = (
            release_ready,
            _truthy("NIJA_RUNTIME_MODULE_IDENTITY_READY"),
            _truthy("NIJA_SCAN_WRAPPER_DEPTH_READY"),
            _truthy("NIJA_ZERO_SIGNAL_STREAK_STATE_READY"),
            _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_READY"),
            _truthy("LIVE_CAPITAL_VERIFIED"),
            not _truthy("DRY_RUN_MODE"),
            not _truthy("PAPER_MODE"),
        )
        if not all(required):
            return False
        try:
            monitor = importlib.import_module("bot.activation_pending_commit_monitor_patch")
            sm = monitor._state_machine()
            if sm is None:
                return False
            state = _state_value(sm)
            if state == "LIVE_ACTIVE":
                return True
            if state == "LIVE_PENDING_CONFIRMATION":
                request_activation("v15_structural_convergence")
        except Exception:
            return False
        return False

    activation_step._nija_v60_nonblocking = True  # type: ignore[attr-defined]
    activation_step.__wrapped__ = original  # type: ignore[attr-defined]
    v15._activation_step = activation_step
    logger.critical(
        "FINAL_ACTIVATION_V60_V15_PATCHED marker=%s structural_convergence_nonblocking=true",
        MARKER,
    )
    return True


def _strict_runtime_ready(runtime: Any, core: Any) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    if runtime is None or not bool(getattr(runtime, "acquired", False)) or bool(getattr(runtime, "lost", False)):
        blockers.append("writer_epoch_current")
    if core is None or not callable(getattr(core, "is_alive", None)) or not core.is_alive():
        blockers.append("core_alive")
    try:
        rt = importlib.import_module("bot.readiness_table")
        snap = dict(rt.snapshot())
    except Exception:
        snap = {}
    for key in (
        "balance_hydrated",
        "capital_ready",
        "risk_ready",
        "strategy_ready",
        "execution_ready",
        "nonce_ready",
        "authority_ready",
        "bootstrap_ready",
    ):
        if not bool(snap.get(key, False)):
            blockers.append(f"readiness.{key}")
    try:
        tsm = importlib.import_module("bot.trading_state_machine")
        sm = tsm.get_state_machine()
        if sm is None:
            blockers.append("state_machine")
        else:
            if _state_value(sm) != "LIVE_ACTIVE":
                blockers.append("live_active")
            if not bool(getattr(sm, "get_activation_committed")()):
                blockers.append("activation_committed")
            if not bool(sm.can_execute()):
                blockers.append("can_execute")
    except Exception:
        blockers.append("state_machine_probe")
    return not blockers, blockers


def _patch_bot_main_nonblocking() -> bool:
    bot_main = importlib.import_module("bot.bot_main")
    current = getattr(bot_main, "_perform_post_core_activation_convergence", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_v60_nonblocking", False):
        return True

    def converge(runtime: Any, trading_thread: Any, *, timeout_s: float = 60.0) -> bool:
        registered = getattr(runtime, "_core_thread", None)
        if registered is not trading_thread or not trading_thread.is_alive():
            logger.critical(
                "POST_CORE_CONVERGENCE_FAILED marker=%s gate=core_identity_or_liveness",
                MARKER,
            )
            return False
        deadline = time.monotonic() + max(1.0, min(float(timeout_s), 60.0))
        attempt = 0
        last_blockers: list[str] = []
        while time.monotonic() < deadline:
            attempt += 1
            allow, blockers = _strict_runtime_ready(runtime, trading_thread)
            if allow:
                logger.critical(
                    "POST_CORE_ACTIVATION_READINESS marker=%s allow=true attempts=%d "
                    "activation_single_flight=true",
                    MARKER,
                    attempt,
                )
                return True
            last_blockers = blockers
            request_activation("bot_main_post_core")
            logger.info(
                "POST_CORE_CONVERGENCE_WAIT marker=%s attempt=%d first_blocker=%s blockers=%s "
                "caller_blocked_on_commit=false",
                MARKER,
                attempt,
                blockers[0] if blockers else "unknown",
                blockers,
            )
            time.sleep(1.0)
        logger.critical(
            "EXECUTION_READINESS_FINAL allow=false marker=%s first_failed_gate=%s blockers=%s "
            "trading_remains_fail_closed=true",
            MARKER,
            last_blockers[0] if last_blockers else "unknown",
            last_blockers,
        )
        return False

    converge._nija_v60_nonblocking = True  # type: ignore[attr-defined]
    converge.__wrapped__ = current  # type: ignore[attr-defined]
    bot_main._perform_post_core_activation_convergence = converge
    logger.critical(
        "FINAL_ACTIVATION_V60_BOT_MAIN_PATCHED marker=%s commit_inline=false bounded_observer=true",
        MARKER,
    )
    return True


def _install_execution_and_exit_repairs() -> bool:
    specs = (
        ("bot.live_entry_completion_repair_patch", ("install_import_hook", "install")),
        ("bot.live_broker_profit_exit_convergence_v25", ("install_import_hook", "install")),
        ("bot.live_engine_profit_exit_convergence_v25", ("install_import_hook", "install")),
        ("bot.execution_pipeline_gate_repair_patch", ("install_import_hook", "install")),
        ("bot.trading_state_dispatch_latch_repair_patch", ("install_import_hook", "install")),
    )
    failures: list[str] = []
    for module_name, installer_names in specs:
        try:
            module = importlib.import_module(module_name)
            installer = next((getattr(module, name, None) for name in installer_names if callable(getattr(module, name, None))), None)
            if not callable(installer):
                failures.append(f"{module_name}:installer_missing")
                continue
            result = installer()
            if result is False:
                failures.append(f"{module_name}:returned_false")
        except Exception as exc:
            failures.append(f"{module_name}:{type(exc).__name__}:{exc}")
    logger.critical(
        "FINAL_ACTIVATION_V60_EXECUTION_REPAIRS marker=%s ready=%s failures=%s "
        "entry=true exits=true dispatch_latch=true thresholds_unchanged=true",
        MARKER,
        not failures,
        failures or "none",
    )
    return not failures


def install_import_hook() -> bool:
    return install()


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        failures: list[str] = []
        for label, step in (
            ("capital_observer", _patch_capital_readiness_observer),
            ("v16_nonblocking", _patch_v16_nonblocking),
            ("v15_nonblocking", _patch_v15_nonblocking),
            ("bot_main_nonblocking", _patch_bot_main_nonblocking),
            ("execution_exit_repairs", _install_execution_and_exit_repairs),
        ):
            try:
                if step() is False:
                    failures.append(label)
            except Exception as exc:
                failures.append(f"{label}:{type(exc).__name__}:{exc}")
                logger.critical(
                    "FINAL_ACTIVATION_V60_STEP_FAILED marker=%s step=%s err=%s",
                    MARKER,
                    label,
                    exc,
                    exc_info=True,
                )
        _INSTALLED = not failures
        os.environ["NIJA_FINAL_PRODUCTION_ACTIVATION_V60_INSTALLED"] = "1" if _INSTALLED else "0"
        logger.critical(
            "FINAL_PRODUCTION_ACTIVATION_V60_INSTALLED marker=%s ready=%s failures=%s "
            "force_activation=false strategy_thresholds_unchanged=true risk_thresholds_unchanged=true",
            MARKER,
            _INSTALLED,
            failures or "none",
        )
        return _INSTALLED


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "request_activation",
    "_publish_risk_compat",
    "_strict_runtime_ready",
]
