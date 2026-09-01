"""
Shared pytest configuration and fixtures for bot/tests/.

This conftest cleans up runtime kill-switch and exchange-protector state
files that some tests create (via the real KillSwitch singleton) so that
each test session starts from a known-clean state and tests don't bleed
state into one another.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths of runtime artifacts that tests may create via the real KillSwitch
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent.parent  # …/Nija
_KILL_SWITCH_ARTIFACTS = [
    _REPO_ROOT / "EMERGENCY_STOP",
    _REPO_ROOT / ".nija_kill_switch_state.json",
    _REPO_ROOT / "data" / "exchange_kill_switch_state.json",
]

# Some writer-authority tests intentionally exercise production paths that arm
# daemon fallback restart timers. In production both defaults are 15s and the
# callbacks terminate the process with os._exit(75). Leaving either real timer
# armed during pytest kills the test runner before pytest can print the assertion
# summary. Give only the test process a long default grace and cancel any timer
# that was actually armed before restoring environment state. Tests that verify
# timer values explicitly override these variables locally.
_WRITER_FALLBACK_RESTART_GRACE_ENV = "NIJA_WRITER_AUTHORITY_FALLBACK_RESTART_GRACE_S"
_WRITER_RUNTIME_RESTART_GRACE_ENV = "NIJA_WRITER_AUTHORITY_RESTART_GRACE_S"
_CORE_REGISTRATION_RESTART_GRACE_ENV = "NIJA_CORE_REGISTRATION_RESTART_GRACE_S"
_STARTUP_VALIDATED_ENV = "NIJA_STARTUP_VALIDATED"
_TEST_WRITER_RESTART_GRACE_S = "3600"
_RESTART_TIMER_NAMES = {
    "entrypoint-writer-unhandled-loss-restart",
    "writer-authority-forced-restart",
}

# The BotMainAuthorityOrderingTests pre-date the explicit startup-validation
# attestation gate. Their mocked main() happy paths intentionally bypass the real
# startup validator, so the test harness must attest that mocked prerequisite or
# the production FSM correctly fails closed before reaching the behavior under
# test. This is deliberately scoped to that one unittest class.
_BOT_MAIN_ORDERING_NODE = (
    "test_entrypoint_writer_authority.py::BotMainAuthorityOrderingTests::"
)

# These legacy main() tests also pre-date the split bootstrap handoff introduced
# by bot_main: STEP 2 now advances only to THREADS_STARTING, while the existing
# RUNNING_SUPERVISED helper is called after the real core thread is registered.
# They additionally pre-date the post-core activation convergence gate. Keep the
# harness scoped to the exact tests whose purpose is writer/thread ordering,
# registration, scan-marker truth, or terminal-writer-loss behavior. Production
# startup, capital hydration, activation convergence, and safety gates are not
# modified.
_BOT_MAIN_PHASE_COMPAT_TESTS = {
    "test_main_returns_nonzero_after_terminal_writer_loss",
    "test_authority_precedes_nonce_and_broker_bootstrap",
    "test_main_registers_core_thread_without_fabricating_scan_started",
    "test_main_does_not_record_scan_started_before_real_scan",
    "test_main_skips_duplicate_registration_for_pre_registered_core_thread",
    "test_main_fail_closed_when_trading_thread_not_alive",
}

# One legacy test still asserts the pre-latch direct restart scheduler. The
# production callback now delegates terminal writer loss to
# terminal_writer_loss_latch, which owns exit/restart sequencing. Quarantine the
# obsolete final assertion with strict xfail while a focused v287 replacement
# test verifies the canonical latch delegation. Strict mode means reintroducing
# the legacy direct scheduler unexpectedly turns this into XPASS and fails CI.
_LEGACY_RESTART_ASSERTION_NODE = (
    "test_entrypoint_writer_authority.py::BotMainAuthorityOrderingTests::"
    "test_writer_acquisition_pins_exact_runtime_before_heartbeat_start"
)


def pytest_collection_modifyitems(items):
    """Mark only the obsolete direct-restart assertion as a strict expected fail."""
    for item in items:
        if item.nodeid.endswith(_LEGACY_RESTART_ASSERTION_NODE):
            item.add_marker(
                pytest.mark.xfail(
                    strict=True,
                    reason=(
                        "legacy direct restart assertion superseded by "
                        "terminal_writer_loss_latch; canonical v287 replacement "
                        "test verifies delegation"
                    ),
                )
            )


def _remove_kill_switch_artifacts() -> None:
    """Delete kill-switch state files if they exist."""
    for path in _KILL_SWITCH_ARTIFACTS:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass  # best-effort cleanup


def _reset_readiness_authority_state() -> None:
    """Keep process-global readiness publication from leaking across tests."""
    try:
        readiness_module = sys.modules.get("bot.readiness_table")
        table = getattr(readiness_module, "_TABLE", None) if readiness_module else None
        if isinstance(table, dict):
            table["authority_ready"] = False
    except Exception:
        pass


def _cancel_writer_restart_timers() -> None:
    """Cancel test-armed process restart timers without changing production code."""
    for thread in list(threading.enumerate()):
        try:
            if getattr(thread, "name", "") in _RESTART_TIMER_NAMES:
                cancel = getattr(thread, "cancel", None)
                if callable(cancel):
                    cancel()
        except Exception:
            pass

    # bot_main keeps its restart timer in a module-global reference. Clear that
    # test-process reference after cancelling so a later test can exercise the
    # scheduling path independently.
    for module_name in ("bot.bot_main", "bot_main"):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        try:
            timer = getattr(module, "_core_registration_restart_timer", None)
            cancel = getattr(timer, "cancel", None)
            if callable(cancel):
                cancel()
            module._core_registration_restart_timer = None
        except Exception:
            pass
        try:
            shutdown_event = getattr(module, "_shutdown_event", None)
            clear = getattr(shutdown_event, "clear", None)
            if callable(clear):
                clear()
            module._process_exit_code = 0
            module._process_exit_reason = ""
        except Exception:
            pass

    for key in (
        "NIJA_PROCESS_EXIT_REQUESTED",
        "NIJA_PROCESS_EXIT_CODE",
        "NIJA_PROCESS_EXIT_REASON",
    ):
        os.environ.pop(key, None)


def _install_bot_main_phase_compat(request, monkeypatch) -> None:
    """Keep legacy bot_main tests focused on the behavior they actually assert."""
    if _BOT_MAIN_ORDERING_NODE not in request.node.nodeid:
        return
    if request.node.name not in _BOT_MAIN_PHASE_COMPAT_TESTS:
        return

    import bot.bot_main as bot_main

    if request.node.name == "test_authority_precedes_nonce_and_broker_bootstrap":
        # This test's existing RUNNING_SUPERVISED mock records the historical
        # "fsm" ordering event. Invoke that mock at the new pre-core phase, then
        # replace the later post-registration call with a no-op success so the
        # ordering assertion still measures one FSM handoff at STEP 2.
        def _precore_order_bridge() -> bool:
            ready = bool(bot_main._advance_bootstrap_fsm_to_running_supervised())
            monkeypatch.setattr(
                bot_main,
                "_advance_bootstrap_fsm_to_running_supervised",
                lambda: True,
            )
            return ready

        monkeypatch.setattr(
            bot_main,
            "_advance_bootstrap_fsm_to_threads_starting",
            _precore_order_bridge,
        )
    else:
        monkeypatch.setattr(
            bot_main,
            "_advance_bootstrap_fsm_to_threads_starting",
            lambda: True,
        )

    # These tests mock broker/FSM/thread prerequisites and do not construct the
    # live readiness table/state-machine inputs required by convergence. Their
    # assertions are upstream of that gate, so isolate the new gate test-only.
    monkeypatch.setattr(
        bot_main,
        "_perform_post_core_activation_convergence",
        lambda *_args, **_kwargs: True,
    )


@pytest.fixture(autouse=True)
def _clean_kill_switch_state(request, monkeypatch):
    """
    Auto-use fixture: remove kill-switch state files and reset process-global
    readiness authority before and after every test so runtime state does not
    bleed into unrelated tests.

    The fixture also prevents production fallback restart timers intentionally
    exercised by writer-authority tests from terminating the pytest process.
    This changes test-process timing only; production defaults are untouched.

    BotMainAuthorityOrderingTests receive a test-only startup-validation
    attestation because those tests mock past the real validator and are testing
    writer/FSM/thread ordering, not startup-validation policy. The exact legacy
    main() tests that pre-date the split pre-core/post-core handoff also receive
    test-only phase compatibility so they do not execute real capital hydration
    or activation convergence while asserting unrelated writer/thread behavior.
    """
    _remove_kill_switch_artifacts()
    _reset_readiness_authority_state()
    _cancel_writer_restart_timers()

    restart_envs = (
        _WRITER_FALLBACK_RESTART_GRACE_ENV,
        _WRITER_RUNTIME_RESTART_GRACE_ENV,
        _CORE_REGISTRATION_RESTART_GRACE_ENV,
    )
    saved_restart_grace = {name: os.environ.get(name) for name in restart_envs}
    for name in restart_envs:
        if saved_restart_grace[name] is None:
            os.environ[name] = _TEST_WRITER_RESTART_GRACE_S

    saved_startup_validated = os.environ.get(_STARTUP_VALIDATED_ENV)
    attestation_scoped = _BOT_MAIN_ORDERING_NODE in request.node.nodeid
    if attestation_scoped:
        os.environ[_STARTUP_VALIDATED_ENV] = "true"

    _install_bot_main_phase_compat(request, monkeypatch)

    yield

    _cancel_writer_restart_timers()
    for name, previous in saved_restart_grace.items():
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous

    if attestation_scoped:
        if saved_startup_validated is None:
            os.environ.pop(_STARTUP_VALIDATED_ENV, None)
        else:
            os.environ[_STARTUP_VALIDATED_ENV] = saved_startup_validated

    _remove_kill_switch_artifacts()
    _reset_readiness_authority_state()

    # Also reset the module-level KillSwitch singleton so its in-memory
    # is_active flag doesn't persist across tests.
    try:
        ks_module = sys.modules.get("bot.kill_switch")
        if ks_module is not None and ks_module._kill_switch is not None:
            ks_module._kill_switch._is_active = False
            ks_module._kill_switch._activation_history = []
    except Exception:
        pass

    # Reset ExchangeKillSwitchProtector singleton.
    try:
        eks_module = sys.modules.get("bot.exchange_kill_switch")
        if eks_module is not None:
            eks_module._protector = None
    except Exception:
        pass
