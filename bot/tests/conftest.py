"""
Shared pytest configuration and fixtures for bot/tests/.

This conftest cleans up runtime kill-switch and exchange-protector state
files that some tests create (via the real KillSwitch singleton) so that
each test session starts from a known-clean state and tests don't bleed
state into one another.
"""

from __future__ import annotations

import sys
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


def _remove_kill_switch_artifacts() -> None:
    """Delete kill-switch state files if they exist."""
    for path in _KILL_SWITCH_ARTIFACTS:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass  # best-effort cleanup


@pytest.fixture(autouse=True)
def _clean_kill_switch_state():
    """
    Auto-use fixture: remove kill-switch state files before and after every
    test so that a test that activates the real KillSwitch does not bleed
    EMERGENCY_STOP or triggered-protector state into unrelated tests.
    """
    _remove_kill_switch_artifacts()
    yield
    _remove_kill_switch_artifacts()

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
