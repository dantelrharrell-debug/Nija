"""Repository-level pytest compatibility hooks.

The nested ``bot/tests/conftest.py`` deliberately stretches writer restart
fallbacks to 3600 seconds so production-style ``os._exit(75)`` timers cannot
kill the test runner.  One focused legacy test explicitly verifies the older
core-registration fallback setting.  During that one test only, remove the
broader writer grace so the production helper can fall back to the explicit
``NIJA_CORE_REGISTRATION_RESTART_GRACE_S`` value supplied by the test.

This file changes test-process environment only.  It does not alter production
restart timing, writer authority, broker execution, or fail-closed behavior.
"""
from __future__ import annotations

import os

import pytest

_TARGET = (
    "bot/tests/test_runtime_startup_handoff_v87.py::"
    "RuntimeStartupHandoffV87Tests::"
    "test_core_registration_restart_is_bounded_and_nonzero"
)
_WRITER_GRACE = "NIJA_WRITER_AUTHORITY_RESTART_GRACE_S"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    if not item.nodeid.endswith(_TARGET):
        yield
        return

    previous = os.environ.pop(_WRITER_GRACE, None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ[_WRITER_GRACE] = previous
        else:
            os.environ.pop(_WRITER_GRACE, None)
