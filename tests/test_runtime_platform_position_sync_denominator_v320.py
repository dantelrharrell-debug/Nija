"""Regression coverage for disconnected registered platform brokers.

The test changes only local Python objects. No broker I/O, orders, or activation.
"""
from __future__ import annotations

from types import SimpleNamespace

from bot import position_sync_core_handoff_v95_patch as v95
from bot import runtime_all_account_position_exit_coverage_v281_patch as v281
from bot import runtime_platform_position_sync_isolation_v320_patch as v320


def patched_status(monkeypatch, connected_status, expected_accounts):
    """Model the v285 strong-proof output and independent v281 registry."""
    def original(_manager):
        statuses = dict(connected_status)
        pending = sorted(k for k, ready in statuses.items() if not ready)
        return not pending, pending, statuses

    monkeypatch.setattr(v95, "position_sync_status", original)
    monkeypatch.setattr(v320, "_is_v285_strong_status", lambda _fn: True)
    monkeypatch.setattr(v281, "_expected_accounts", lambda _manager: expected_accounts)
    assert v320._patch_v95_after_v285()
    return v95.position_sync_status


def test_disconnected_kraken_never_disappears_from_platform_readiness(monkeypatch):
    status = patched_status(
        monkeypatch,
        {"platform:coinbase": True, "platform:okx": True},
        {"platform:coinbase": object(), "platform:kraken": None, "platform:okx": object()},
    )
    manager = SimpleNamespace()
    ready, pending, platforms = status(manager)
    assert ready is False
    assert pending == ["platform:kraken"]
    assert platforms["platform:kraken"] is False
    assert manager._nija_user_position_sync_status_v320 == {}


def test_failed_to_initialize_platform_stays_in_denominator(monkeypatch):
    status = patched_status(
        monkeypatch, {"platform:coinbase": True},
        {"platform:coinbase": object(), "platform:kraken": None},
    )
    ready, pending, _ = status(SimpleNamespace())
    assert ready is False
    assert pending == ["platform:kraken"]


def test_strong_proof_failure_is_not_promoted_to_ready(monkeypatch):
    status = patched_status(
        monkeypatch, {"platform:coinbase": True, "platform:kraken": False},
        {"platform:coinbase": object(), "platform:kraken": object()},
    )
    ready, pending, platforms = status(SimpleNamespace())
    assert ready is False
    assert pending == ["platform:kraken"]
    assert platforms["platform:kraken"] is False


def test_unavailable_account_registry_fails_closed(monkeypatch):
    status = patched_status(
        monkeypatch, {"platform:coinbase": True}, None,
    )
    assert status(SimpleNamespace())[0] is False


def test_empty_registry_fails_closed_even_with_connected_platform(monkeypatch):
    status = patched_status(
        monkeypatch, {"platform:coinbase": True}, {},
    )
    assert status(SimpleNamespace())[0] is False


def test_unexpected_registry_error_fails_closed(monkeypatch):
    status = patched_status(
        monkeypatch, {"platform:coinbase": True},
        {"platform:coinbase": object()},
    )
    def fail(_manager):
        raise RuntimeError("registry_unavailable")
    monkeypatch.setattr(v281, "_expected_accounts", fail)
    assert status(SimpleNamespace())[0] is False


def test_user_account_failure_isolated_from_platform_readiness(monkeypatch):
    status = patched_status(
        monkeypatch,
        {"platform:coinbase": True, "platform:kraken": True, "platform:okx": True,
         "user:unverified:kraken": False},
        {"platform:coinbase": object(), "platform:kraken": object(),
         "platform:okx": object(), "user:unverified:kraken": None},
    )
    manager = SimpleNamespace()
    ready, pending, platforms = status(manager)
    assert ready is True
    assert pending == []
    assert "user:unverified:kraken" not in platforms
    assert manager._nija_user_position_sync_status_v320["user:unverified:kraken"] is False
