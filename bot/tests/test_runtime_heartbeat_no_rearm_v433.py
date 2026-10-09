"""Offline live-heartbeat policy regressions; no broker access or orders."""
from __future__ import annotations

import pytest

from bot import runtime_heartbeat_probe_pipeline_bridge_v197_patch as scheduler


@pytest.mark.parametrize("first_required", ["false", "true"])
@pytest.mark.parametrize("previous", ["false", "true"])
def test_absent_paid_order_opt_in_cannot_rearm_heartbeat(monkeypatch, first_required, previous):
    monkeypatch.setattr(scheduler, "_resolved_runtime_mode", lambda: (True, "live", "unit"))
    monkeypatch.setenv("NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS", "false")
    monkeypatch.setenv("HEARTBEAT_TRADE", previous)
    monkeypatch.setenv("HEARTBEAT_REQUIRED_FIRST_ACTIVATION", first_required)

    assert scheduler._align_required_heartbeat_scheduler_policy()
    assert scheduler._env_truthy("HEARTBEAT_TRADE") is False


def test_explicit_two_flag_operator_opt_in_can_arm_scheduler(monkeypatch):
    monkeypatch.setattr(scheduler, "_resolved_runtime_mode", lambda: (True, "live", "unit"))
    monkeypatch.setenv("NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS", "true")
    monkeypatch.setenv("HEARTBEAT_TRADE", "false")
    monkeypatch.setenv("HEARTBEAT_REQUIRED_FIRST_ACTIVATION", "false")

    assert scheduler._align_required_heartbeat_scheduler_policy()
    assert scheduler._env_truthy("HEARTBEAT_TRADE") is True


@pytest.mark.parametrize("mode", ["paper", "monitor", "dry_run"])
def test_non_live_modes_do_not_arm_scheduler(monkeypatch, mode):
    monkeypatch.setattr(scheduler, "_resolved_runtime_mode", lambda: (True, mode, "unit"))
    monkeypatch.setenv("NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS", "true")
    monkeypatch.setenv("HEARTBEAT_TRADE", "false")
    monkeypatch.setenv("HEARTBEAT_REQUIRED_FIRST_ACTIVATION", "false")

    assert scheduler._align_required_heartbeat_scheduler_policy()
    assert scheduler._env_truthy("HEARTBEAT_TRADE") is False


def test_unresolved_runtime_keeps_stale_startup_opt_out(monkeypatch):
    monkeypatch.setattr(scheduler, "_resolved_runtime_mode", lambda: (False, "unresolved", "unit"))
    monkeypatch.setenv("NIJA_ALLOW_LIVE_HEARTBEAT_ORDERS", "false")
    monkeypatch.setenv("HEARTBEAT_TRADE", "true")
    monkeypatch.setenv("HEARTBEAT_REQUIRED_FIRST_ACTIVATION", "true")

    assert scheduler._align_required_heartbeat_scheduler_policy() is False
    assert scheduler._env_truthy("HEARTBEAT_TRADE") is False
