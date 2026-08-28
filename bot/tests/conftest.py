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
_TEST_WRITER_RESTART_GRACE_S = "3600"
_RESTART_TIMER_NAMES = {
    "entrypoint-writer-unhandled-loss-restart",
    "writer-authority-forced-restart",
}


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


@pytest.fixture(autouse=True)
def _clean_kill_switch_state():
    """
    Auto-use fixture: remove kill-switch state files and reset process-global
    readiness authority before and after every test so runtime state does not
    bleed into unrelated tests.

    The fixture also prevents production fallback restart timers intentionally
    exercised by writer-authority tests from terminating the pytest process.
    This changes test-process timing only; production defaults are untouched.
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

    yield

    _cancel_writer_restart_timers()
    for name, previous in saved_restart_grace.items():
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous

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
