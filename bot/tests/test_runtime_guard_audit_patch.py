from __future__ import annotations

import os
from unittest.mock import patch

import bot.runtime_guard_audit_patch as audit


def test_ready_when_all_mandatory_guards_are_true():
    env = {name: "1" for name in audit._REQUIRED}
    ready, missing = audit._ready(env)
    assert ready is True
    assert missing == []


def test_missing_guard_is_reported():
    env = {name: "1" for name in audit._REQUIRED}
    env[audit._REQUIRED[1]] = "0"
    ready, missing = audit._ready(env)
    assert ready is False
    assert missing == [audit._REQUIRED[1]]


def test_explicit_writer_loss_makes_runtime_audit_not_ready():
    env = {name: "1" for name in audit._REQUIRED}
    env.update(
        {
            "NIJA_WRITER_LEASE_ACQUIRED": "0",
            "NIJA_WRITER_HEARTBEAT_ACTIVE": "0",
            "NIJA_CANONICAL_WRITER_FIRST_V59_READY": "1",
        }
    )

    ready, missing = audit._ready(env)

    assert ready is False
    assert missing == list(audit._DYNAMIC_WRITER_REQUIRED)


def test_live_active_requires_execution_authority():
    env = {name: "1" for name in audit._REQUIRED}
    env.update(
        {
            "NIJA_WRITER_LEASE_ACQUIRED": "1",
            "NIJA_WRITER_HEARTBEAT_ACTIVE": "1",
            "NIJA_RUNTIME_TRADING_STATE": "LIVE_ACTIVE",
            "NIJA_RUNTIME_EXECUTION_AUTHORITY": "0",
            "NIJA_BROKER_RUNTIME_PREFLIGHT_READY": "1",
            "NIJA_EXECUTION_LIFECYCLE_CANARY_PASSED": "1",
        }
    )

    ready, missing = audit._ready(env)

    assert ready is False
    assert missing == ["NIJA_RUNTIME_EXECUTION_AUTHORITY"]


def test_live_active_requires_broker_preflight_and_lifecycle_canary():
    env = {name: "1" for name in audit._REQUIRED}
    env.update(
        {
            "NIJA_WRITER_LEASE_ACQUIRED": "1",
            "NIJA_WRITER_HEARTBEAT_ACTIVE": "1",
            "NIJA_RUNTIME_TRADING_STATE": "LIVE_ACTIVE",
            "NIJA_RUNTIME_EXECUTION_AUTHORITY": "1",
            "NIJA_BROKER_RUNTIME_PREFLIGHT_READY": "0",
            "NIJA_EXECUTION_LIFECYCLE_CANARY_PASSED": "0",
        }
    )

    ready, missing = audit._ready(env)

    assert ready is False
    assert missing == [
        "NIJA_BROKER_RUNTIME_PREFLIGHT_READY",
        "NIJA_EXECUTION_LIFECYCLE_CANARY_PASSED",
    ]


def test_pre_acquisition_zero_writer_flags_do_not_break_guard_install():
    env = {name: "1" for name in audit._REQUIRED}
    env.update(
        {
            "NIJA_WRITER_LEASE_ACQUIRED": "0",
            "NIJA_WRITER_HEARTBEAT_ACTIVE": "0",
            "NIJA_PREBOT_WRITER_AUTHORITY_READY": "0",
            "NIJA_CANONICAL_WRITER_FIRST_V59_READY": "0",
        }
    )

    ready, missing = audit._ready(env)

    assert ready is True
    assert missing == []


def test_emit_fails_closed_after_explicit_writer_loss():
    env = {name: "1" for name in audit._REQUIRED}
    env.update(
        {
            "NIJA_WRITER_LEASE_ACQUIRED": "0",
            "NIJA_WRITER_HEARTBEAT_ACTIVE": "0",
            "NIJA_CANONICAL_WRITER_FIRST_V59_READY": "1",
            "NIJA_RUNTIME_TRADING_STATE": "LIVE_ACTIVE",
            "NIJA_RUNTIME_EXECUTION_AUTHORITY": "1",
            "NIJA_BROKER_RUNTIME_PREFLIGHT_READY": "1",
            "NIJA_EXECUTION_LIFECYCLE_CANARY_PASSED": "1",
        }
    )

    with patch.dict(os.environ, env, clear=True):
        ready = audit._emit()

        assert ready is False
        assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
        assert os.environ["NIJA_RUNTIME_TRADING_STATE"] == "OFF"
