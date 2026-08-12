"""Final production activation repair v58.

Narrow corrective layer for the production failures observed on 2026-08-12:

* publish independently proven readiness keys monotonically instead of waiting
  for every readiness proof to become true at once;
* prevent the legacy stalled-writer guard from destructively releasing the
  canonical writer lease on the canonical Render startup path;
* require an exact live core before any helper may finalize RUNNING_SUPERVISED;
* classify the real writer re-election/core-death reason as terminal;
* enforce strict post-core LIVE success before TRADING_ENGINE_READY may open;
* suppress new Kraken private I/O after terminal writer loss and discard a
  balance result that crosses a writer-epoch boundary.

This module does not lower strategy, risk, venue, capital, nonce, SEAK, or
kill-switch gates and never forces LIVE_ACTIVE.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.final_production_activation_repair_v58")
MARKER = "20260812-final-production-activation-v58"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_READINESS_KEYS = (
    "broker_connected",
    "balance_hydrated",
    "authority_ready",
    "capital_ready",
    "risk_ready",
    "strategy_ready",
    "execution_ready",
    "nonce_ready",
    "bootstrap_ready",
)
_LOCK = threading.RLock()
_INSTALLED = False


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _canonical_fast_path() -> bool:
    return bool(
        _truthy("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH")
        and _truthy("NIJA_DEFER_RUNTIME_SITE_HOOKS")
    )


def _value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _readiness_table() -> ModuleType:
    try:
        return importlib.import_module("bot.readiness_table")
    except ImportError:
        return importlib.import_module("readiness_table")


def _bootstrap_state() -> str:
    try:
        try:
            module = importlib.import_module("bot.bootstrap_state_machine")
        except ImportError:
            module = importlib.import_module("bootstrap_state_machine")
        return _value(module.get_bootstrap_fsm().state).upper() or "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _emit_readiness_diagnostics(proofs: dict[str, bool]) -> None:
    risk_flags = {
        "pre_dispatch_risk_sizing_ready": _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_READY"),
        "pre_dispatch_risk_sizing_fail_closed": _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_FAIL_CLOSED"),
        "downstream_risk_governor_v2_installed": _truthy("NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_INSTALLED"),
    }
    if not bool(proofs.get("risk_ready")):
        first = next((name for name, ready in risk_flags.items() if not ready), "unknown")
        LOGGER.warning(
            "RISK_READINESS_DIAGNOSTIC marker=%s pre_dispatch_risk_sizing_ready=%s "
            "pre_dispatch_risk_sizing_fail_closed=%s downstream_risk_governor_v2_installed=%s "
            "first_failed_requirement=%s",
            MARKER,
            risk_flags["pre_dispatch_risk_sizing_ready"],
            risk_flags["pre_dispatch_risk_sizing_fail_closed"],
            risk_flags["downstream_risk_governor_v2_installed"],
            first,
        )

    bootstrap_flags = {
        "bootstrap_supervised": _bootstrap_state() == "RUNNING_SUPERVISED",
        "runtime_module_identity_ready": _truthy("NIJA_RUNTIME_MODULE_IDENTITY_READY"),
        "scan_wrapper_depth_ready": _truthy("NIJA_SCAN_WRAPPER_DEPTH_READY"),
        "zero_signal_streak_state_ready": _truthy("NIJA_ZERO_SIGNAL_STREAK_STATE_READY"),
        "pre_dispatch_risk_sizing_ready": _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_READY"),
    }
    if not bool(proofs.get("bootstrap_ready")):
        first = next((name for name, ready in bootstrap_flags.items() if not ready), "unknown")
        LOGGER.warning(
            "BOOTSTRAP_READINESS_DIAGNOSTIC marker=%s bootstrap_state=%s "
            "runtime_module_identity_ready=%s scan_wrapper_depth_ready=%s "
            "zero_signal_streak_state_ready=%s pre_dispatch_risk_sizing_ready=%s "
            "first_failed_requirement=%s",
            MARKER,
            _bootstrap_state(),
            bootstrap_flags["runtime_module_identity_ready"],
            bootstrap_flags["scan_wrapper_depth_ready"],
            bootstrap_flags["zero_signal_streak_state_ready"],
            bootstrap_flags["pre_dispatch_risk_sizing_ready"],
            first,
        )


def _incremental_mark_proven_readiness(proofs: dict[str, bool]) -> tuple[bool, list[str]]:
    """Publish each independently proven readiness key immediately."""
    try:
        table = _readiness_table()
        snapshot = getattr(table, "snapshot")
        mark_ready = getattr(table, "mark_ready")
        before = dict(snapshot())
        for key in _READINESS_KEYS:
            if bool(proofs.get(key)):
                mark_ready(key)
        after = dict(snapshot())
        pending = [key for key in _READINESS_KEYS if not bool(after.get(key, False))]
        os.environ["NIJA_PREACTIVATION_READINESS_V16_READY"] = "0" if pending else "1"
        if bool(proofs.get("authority_ready")):
            os.environ["NIJA_AUTHORITY_READY"] = "1"
        if bool(proofs.get("nonce_ready")):
            os.environ["NIJA_NONCE_READY"] = "1"
            os.environ["NIJA_RUNTIME_NONCE_READY"] = "1"
        _emit_readiness_diagnostics(proofs)
        LOGGER.critical(
            "PREACTIVATION_READINESS_V58_INCREMENTAL marker=%s before=%s after=%s "
            "pending=%s proofs=%s",
            MARKER,
            before,
            after,
            pending,
            proofs,
        )
        if not pending:
            LOGGER.critical(
                "PREACTIVATION_READY marker=%s authority_ready=%s nonce_ready=%s "
                "writer_authority=confirmed blockers_cleared=true",
                MARKER,
                bool(proofs.get("authority_ready")),
                bool(proofs.get("nonce_ready")),
            )
        return not pending, pending
    except Exception as exc:
        os.environ["NIJA_PREACTIVATION_READINESS_V16_READY"] = "0"
        LOGGER.critical(
            "PREACTIVATION_READINESS_V58_ERROR marker=%s err=%s",
            MARKER,
            exc,
            exc_info=True,
        )
        return False, [f"readiness_table_error:{exc}"]


def _patch_readiness() -> bool:
    target = importlib.import_module("preactivation_readiness_convergence_v16_patch")
    target._mark_proven_readiness = _incremental_mark_proven_readiness
    LOGGER.critical(
        "FINAL_ACTIVATION_V58_READINESS_PATCHED marker=%s mode=incremental_monotonic",
        MARKER,
    )
    return True


def _canonical_core_registered(bot_main: ModuleType | None = None) -> bool:
    try:
        bot_main = bot_main or importlib.import_module("bot.bot_main")
        runtime = getattr(bot_main, "_writer_authority_runtime", None)
        core = getattr(runtime, "_core_thread", None) if runtime is not None else None
        return bool(
            runtime is not None
            and getattr(runtime, "acquired", False)
            and not getattr(runtime, "lost", False)
            and core is not None
            and callable(getattr(core, "is_alive", None))
            and core.is_alive()
        )
    except Exception:
        return False


def _patch_stalled_writer_guard() -> bool:
    guard = importlib.import_module("bot.stalled_writer_release_guard_v22")
    original_should_release = getattr(guard, "_should_release")
    original_bootstrap_progression = getattr(guard, "_attempt_bootstrap_progression")
    original_trigger_release = getattr(guard, "_trigger_release")

    @wraps(original_should_release)
    def should_release(snapshot: Any, elapsed_s: float, timeout_s: float) -> bool:
        if _canonical_fast_path():
            if elapsed_s >= timeout_s:
                LOGGER.critical(
                    "WRITER_RELEASE_SUPPRESSED_DURING_CANONICAL_STARTUP marker=%s "
                    "elapsed_s=%.1f timeout_s=%.1f state=%s generation=%s "
                    "bot_main_owns_release=true",
                    MARKER,
                    elapsed_s,
                    timeout_s,
                    getattr(snapshot, "state", "unknown"),
                    getattr(snapshot, "generation", "0"),
                )
            return False
        return bool(original_should_release(snapshot, elapsed_s, timeout_s))

    @wraps(original_bootstrap_progression)
    def bootstrap_progression(source: str) -> bool:
        if _canonical_fast_path() and not _canonical_core_registered():
            LOGGER.warning(
                "STALLED_WRITER_BOOTSTRAP_FINALIZATION_SUPPRESSED marker=%s "
                "source=%s reason=canonical_core_not_registered bot_main_owns_handoff=true",
                MARKER,
                source,
            )
            return False
        return bool(original_bootstrap_progression(source))

    @wraps(original_trigger_release)
    def trigger_release(bot_main: Any, snapshot: Any, reason: str) -> None:
        if _canonical_fast_path():
            LOGGER.critical(
                "STALLED_WRITER_DIRECT_RELEASE_SUPPRESSED marker=%s reason=%s "
                "generation=%s bot_main_owns_release=true",
                MARKER,
                reason,
                getattr(snapshot, "generation", "0"),
            )
            request_exit = getattr(bot_main, "request_process_exit", None)
            if callable(request_exit):
                request_exit(
                    f"stalled_writer_guard:{reason}",
                    exit_code=75,
                    terminal_startup_failure=True,
                )
            return
        original_trigger_release(bot_main, snapshot, reason)

    guard._should_release = should_release
    guard._attempt_bootstrap_progression = bootstrap_progression
    guard._trigger_release = trigger_release
    os.environ["NIJA_STALLED_WRITER_CANONICAL_DIAGNOSTIC_ONLY"] = "1"
    LOGGER.critical(
        "FINAL_ACTIVATION_V58_STALLED_WRITER_PATCHED marker=%s "
        "canonical_direct_release=false canonical_bootstrap_owner=bot_main",
        MARKER,
    )
    return True


def _patch_terminal_writer_loss() -> bool:
    latch = importlib.import_module("bot.terminal_writer_loss_latch")
    terminal = {
        str(item).lower()
        for item in getattr(latch, "_TERMINAL_REASON_KEYWORDS", frozenset())
    }
    terminal.update(
        {
            "core_thread_dead",
            "writer_lock_released_for_reelection",
            "core_thread_died",
        }
    )
    latch._TERMINAL_REASON_KEYWORDS = frozenset(terminal)
    original = getattr(latch, "_is_terminal_proof")

    @wraps(original)
    def is_terminal_proof(reason: str) -> bool:
        lower = str(reason or "").lower()
        transients = {
            str(item).lower()
            for item in getattr(latch, "_TRANSIENT_KEYWORDS", frozenset())
        }
        if any(keyword in lower for keyword in transients):
            return False
        if (
            lower.startswith("writer_lock_released_for_reelection:")
            and "core_thread_dead" in lower
        ):
            return True
        return any(keyword in lower for keyword in latch._TERMINAL_REASON_KEYWORDS)

    latch._is_terminal_proof = is_terminal_proof
    LOGGER.critical(
        "FINAL_ACTIVATION_V58_TERMINAL_CLASSIFIER_PATCHED marker=%s "
        "production_core_dead_reason=terminal",
        MARKER,
    )
    return True


def _strict_live_proofs(runtime: Any, trading_thread: Any) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    if trading_thread is None or not callable(getattr(trading_thread, "is_alive", None)) or not trading_thread.is_alive():
        blockers.append("core_thread_alive")
    if runtime is None or not getattr(runtime, "acquired", False) or getattr(runtime, "lost", False):
        blockers.append("writer_epoch_current")

    sm = None
    try:
        from bot.trading_state_machine import get_state_machine, resolve_runtime_mode_safe
        sm = get_state_machine()
    except Exception:
        try:
            from trading_state_machine import get_state_machine, resolve_runtime_mode_safe  # type: ignore[import]
            sm = get_state_machine()
        except Exception:
            sm = None
    if sm is None:
        blockers.append("trading_state_machine")
        return False, blockers

    committed = bool(getattr(sm, "_activation_committed", False))
    if not committed:
        blockers.append("activation_committed")
    try:
        if not bool(sm.is_live_trading_active()):
            blockers.append("live_active")
    except Exception:
        blockers.append("live_active")
    try:
        if not bool(sm.can_dispatch_trades()):
            blockers.append("can_dispatch_trades")
    except Exception:
        blockers.append("can_dispatch_trades")
    try:
        if not bool(sm.can_execute()):
            blockers.append("can_execute")
    except Exception:
        blockers.append("can_execute")

    try:
        try:
            from bot.startup_coordinator import get_global_state
        except ImportError:
            from startup_coordinator import get_global_state  # type: ignore[import]
        state = _value(sm.get_current_state()) or "UNKNOWN"
        snap = get_global_state().capture(trading_state=state, activation_intent=True)
        startup = snap.startup
        runtime_authority = _value(startup.runtime_authority_state).upper()
        lifecycle = _value(startup.lifecycle_phase).upper()
        if not runtime_authority.endswith("EXECUTING"):
            blockers.append("coordinator_executing")
        if not lifecycle.endswith("LIVE"):
            blockers.append("lifecycle_live")
        if not bool(startup.dispatch_enabled):
            blockers.append("dispatch_enabled")
        if not bool(startup.execution_permitted):
            blockers.append("execution_permitted")
    except Exception:
        blockers.append("coordinator_snapshot")

    return not blockers, blockers


def _patch_bot_main() -> bool:
    bot_main = importlib.import_module("bot.bot_main")
    original_handoff = getattr(bot_main, "_advance_bootstrap_fsm_to_running_supervised")
    original_convergence = getattr(bot_main, "_perform_post_core_activation_convergence")

    @wraps(original_handoff)
    def guarded_handoff() -> bool:
        if not _canonical_core_registered(bot_main):
            LOGGER.critical(
                "BOOTSTRAP_SUPERVISED_HANDOFF_BLOCKED marker=%s "
                "reason=exact_live_core_not_registered state_unchanged=true",
                MARKER,
            )
            return False
        return bool(original_handoff())

    @wraps(original_convergence)
    def strict_convergence(runtime: Any, trading_thread: Any, *, timeout_s: float = 60.0) -> bool:
        base = bool(original_convergence(runtime, trading_thread, timeout_s=timeout_s))
        if not base:
            return False
        live = _truthy("LIVE_CAPITAL_VERIFIED") and not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE")
        if not live:
            return True
        allow, blockers = _strict_live_proofs(runtime, trading_thread)
        if not allow:
            LOGGER.critical(
                "EXECUTION_READINESS_FINAL allow=false marker=%s "
                "first_failed_gate=%s blockers=%s strict_live_proofs=true "
                "trading_remains_fail_closed=true",
                MARKER,
                blockers[0] if blockers else "unknown",
                blockers,
            )
            return False
        LOGGER.critical(
            "EXECUTION_READINESS_FINAL allow=true marker=%s strict_live_proofs=true "
            "activation_committed=true live_active=true coordinator=EXECUTING lifecycle=LIVE",
            MARKER,
        )
        return True

    bot_main._advance_bootstrap_fsm_to_running_supervised = guarded_handoff
    bot_main._perform_post_core_activation_convergence = strict_convergence
    LOGGER.critical(
        "FINAL_ACTIVATION_V58_BOT_MAIN_PATCHED marker=%s "
        "precore_supervised=false strict_postcore_success=true",
        MARKER,
    )
    return True


def _restore_attr(instance: Any, name: str, existed: bool, value: Any) -> None:
    try:
        if existed:
            setattr(instance, name, value)
        elif hasattr(instance, name):
            delattr(instance, name)
    except Exception:
        pass


def _patch_kraken_private_io() -> bool:
    """Fence common Kraken private/balance methods at the writer epoch boundary."""
    try:
        broker_module = importlib.import_module("bot.broker_manager")
    except ImportError:
        broker_module = importlib.import_module("broker_manager")
    cls = getattr(broker_module, "KrakenBroker", None)
    if not isinstance(cls, type):
        return False

    patched = 0
    balance_names = ("get_account_balance", "get_detailed_balance", "fetch_balance")
    boundary_names = ("_private_request", "_query_private", "_request_private", "private_request")

    for name in balance_names:
        original = getattr(cls, name, None)
        if not callable(original) or getattr(original, "_nija_v58_epoch_guard", False):
            continue

        @wraps(original)
        def guarded_balance(self: Any, *args: Any, __original: Callable[..., Any] = original, __name: str = name, **kwargs: Any) -> Any:
            if os.environ.get("NIJA_PRIVATE_IO_STOP", "0") == "1":
                LOGGER.critical(
                    "PRIVATE_IO_SUPPRESSED marker=%s broker=kraken operation=%s "
                    "reason=terminal_writer_loss broker_io_attempted=false",
                    MARKER,
                    __name,
                )
                cached = getattr(self, "_last_known_balance", 0.0)
                return cached if cached is not None else 0.0

            generation_before = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "0")
            token_before = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "")
            had_balance = hasattr(self, "_last_known_balance")
            balance_before = getattr(self, "_last_known_balance", None)
            had_updated = hasattr(self, "_balance_last_updated")
            updated_before = getattr(self, "_balance_last_updated", None)
            result = __original(self, *args, **kwargs)
            generation_after = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "0")
            token_after = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "")
            epoch_ended = bool(
                os.environ.get("NIJA_PRIVATE_IO_STOP", "0") == "1"
                or not token_after
                or generation_after in {"", "0"}
                or generation_after != generation_before
                or token_after != token_before
            )
            if epoch_ended:
                _restore_attr(self, "_last_known_balance", had_balance, balance_before)
                _restore_attr(self, "_balance_last_updated", had_updated, updated_before)
                LOGGER.critical(
                    "PRIVATE_IO_RESPONSE_DISCARDED marker=%s broker=kraken operation=%s "
                    "reason=authority_epoch_ended generation_before=%s generation_after=%s",
                    MARKER,
                    __name,
                    generation_before,
                    generation_after,
                )
                return balance_before if balance_before is not None else 0.0
            return result

        setattr(guarded_balance, "_nija_v58_epoch_guard", True)
        setattr(cls, name, guarded_balance)
        patched += 1

    for name in boundary_names:
        original = getattr(cls, name, None)
        if not callable(original) or getattr(original, "_nija_v58_epoch_guard", False):
            continue

        @wraps(original)
        def guarded_private(self: Any, *args: Any, __original: Callable[..., Any] = original, __name: str = name, **kwargs: Any) -> Any:
            if os.environ.get("NIJA_PRIVATE_IO_STOP", "0") == "1":
                LOGGER.critical(
                    "PRIVATE_IO_SUPPRESSED marker=%s broker=kraken operation=%s "
                    "reason=terminal_writer_loss broker_io_attempted=false",
                    MARKER,
                    __name,
                )
                raise RuntimeError("Kraken private I/O suppressed after terminal writer loss")
            generation_before = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "0")
            token_before = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "")
            result = __original(self, *args, **kwargs)
            generation_after = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "0")
            token_after = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "")
            if (
                os.environ.get("NIJA_PRIVATE_IO_STOP", "0") == "1"
                or not token_after
                or generation_after in {"", "0"}
                or generation_after != generation_before
                or token_after != token_before
            ):
                LOGGER.critical(
                    "PRIVATE_IO_RESPONSE_DISCARDED marker=%s broker=kraken operation=%s "
                    "reason=authority_epoch_ended generation_before=%s generation_after=%s",
                    MARKER,
                    __name,
                    generation_before,
                    generation_after,
                )
                raise RuntimeError("Kraken private response discarded after writer epoch ended")
            return result

        setattr(guarded_private, "_nija_v58_epoch_guard", True)
        setattr(cls, name, guarded_private)
        patched += 1

    LOGGER.critical(
        "FINAL_ACTIVATION_V58_KRAKEN_PRIVATE_IO_PATCHED marker=%s methods=%d",
        MARKER,
        patched,
    )
    return True


def install_import_hook() -> bool:
    return install()


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        steps = (
            ("readiness", _patch_readiness),
            ("stalled_writer", _patch_stalled_writer_guard),
            ("terminal_loss", _patch_terminal_writer_loss),
            ("bot_main", _patch_bot_main),
            ("kraken_private_io", _patch_kraken_private_io),
        )
        failures: list[str] = []
        for label, step in steps:
            try:
                if step() is False:
                    failures.append(label)
            except Exception as exc:
                failures.append(f"{label}:{type(exc).__name__}:{exc}")
                LOGGER.critical(
                    "FINAL_ACTIVATION_V58_STEP_FAILED marker=%s step=%s err=%s",
                    MARKER,
                    label,
                    exc,
                    exc_info=True,
                )
        _INSTALLED = not failures
        os.environ["NIJA_FINAL_PRODUCTION_ACTIVATION_V58_INSTALLED"] = "1" if _INSTALLED else "0"
        LOGGER.critical(
            "FINAL_PRODUCTION_ACTIVATION_V58_INSTALLED marker=%s ready=%s failures=%s "
            "risk_thresholds_unchanged=true strategy_thresholds_unchanged=true",
            MARKER,
            _INSTALLED,
            failures or "none",
        )
        return _INSTALLED


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_incremental_mark_proven_readiness",
    "_canonical_core_registered",
    "_strict_live_proofs",
]
