from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from bot import capital_publication_deadline_v137_patch as v137


@dataclass(frozen=True)
class FakeStatus:
    accepted: bool
    stale: bool
    reason: str
    timestamp: datetime | None
    expiry: datetime | None


class FakeAuthority:
    def __init__(self, status: FakeStatus, snapshot=None) -> None:
        self.status = status
        self._last_typed_snapshot = snapshot

    def get_snapshot_publication_status(self) -> FakeStatus:
        return self.status

    def get_typed_snapshot(self):
        return self._last_typed_snapshot


class FakeCoordinator:
    def __init__(self, snapshot=None) -> None:
        self._in_flight = False
        self.snapshot = snapshot
        self.calls: list[tuple[dict[str, object], str, float]] = []

    def execute_refresh(self, *, broker_map, trigger, open_exposure_usd):
        self.calls.append((dict(broker_map), str(trigger), float(open_exposure_usd)))
        return self.snapshot


class FakeLock:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _manager(coordinator=None):
    registration = SimpleNamespace(is_set=lambda: True)
    return SimpleNamespace(
        capital_watchdog_interval_s=10.0,
        _capital_coordinator=coordinator,
        _broker_registration_complete=registration,
        _startup_lock_released=True,
        _platform_brokers={},
        user_brokers={},
        _capital_state_lock=FakeLock(),
        _capital_ready=True,
        _capital_last_refresh_ts=0.0,
        _capital_last_valid_brokers=0,
    )


def test_refresh_is_due_before_expiry_with_v78_budget_headroom(monkeypatch) -> None:
    now = datetime(2026, 8, 17, 20, 52, 0, tzinfo=timezone.utc)
    authority = FakeAuthority(
        FakeStatus(
            accepted=True,
            stale=False,
            reason="accepted",
            timestamp=now - timedelta(seconds=35),
            expiry=now + timedelta(seconds=55),
        )
    )
    manager = _manager()
    monkeypatch.setattr(v137, "_freshness_ttl_seconds", lambda: 90.0)
    monkeypatch.setattr(v137, "_fetch_budget_seconds", lambda: 50.0)

    due, meta = v137._publication_refresh_due(authority, manager, now=now)

    assert due is True
    assert meta["due_reason"] == "pre_expiry_headroom"
    assert meta["headroom_s"] == 60.0
    assert meta["remaining_s"] == 55.0


def test_refresh_is_not_due_while_publication_has_safe_headroom(monkeypatch) -> None:
    now = datetime(2026, 8, 17, 20, 52, 0, tzinfo=timezone.utc)
    authority = FakeAuthority(
        FakeStatus(
            accepted=True,
            stale=False,
            reason="accepted",
            timestamp=now - timedelta(seconds=10),
            expiry=now + timedelta(seconds=80),
        )
    )
    manager = _manager()
    monkeypatch.setattr(v137, "_freshness_ttl_seconds", lambda: 90.0)
    monkeypatch.setattr(v137, "_fetch_budget_seconds", lambda: 50.0)

    due, meta = v137._publication_refresh_due(authority, manager, now=now)

    assert due is False
    assert meta["due_reason"] == "not_due"
    assert meta["remaining_s"] == 80.0


def test_elapsed_expiry_is_due_even_if_status_stale_flag_lagged() -> None:
    now = datetime(2026, 8, 17, 20, 52, 0, tzinfo=timezone.utc)
    authority = FakeAuthority(
        FakeStatus(
            accepted=True,
            stale=False,
            reason="accepted",
            timestamp=now - timedelta(seconds=91),
            expiry=now - timedelta(seconds=1),
        )
    )

    due, meta = v137._publication_refresh_due(authority, _manager(), now=now)

    assert due is True
    assert meta["stale"] is True
    assert meta["reason"] == "expired_after_publish"


def test_inflight_mabm_refresh_is_read_only_and_skips_legacy_fallback(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    snapshot = SimpleNamespace(
        real_capital=468.02,
        broker_count=3,
        broker_balances={"kraken": 468.02},
    )
    authority = FakeAuthority(
        FakeStatus(True, False, "accepted", now, now + timedelta(seconds=70)),
        snapshot=snapshot,
    )
    monkeypatch.setattr(v137, "_authority", lambda: authority)

    original_calls: list[str] = []

    class FakeManager:
        def refresh_capital_authority(self, trigger="manual"):
            original_calls.append(str(trigger))
            return {"ready": 1.0, "total_capital": 999.0, "valid_brokers": 99.0}

    coordinator = FakeCoordinator()
    coordinator._in_flight = True
    manager = FakeManager()
    manager._capital_coordinator = coordinator

    assert v137._patch_manager_class(FakeManager)
    result = manager.refresh_capital_authority(trigger="watchdog")

    assert original_calls == []
    assert result["ready"] == 1.0
    assert result["total_capital"] == 468.02
    assert result["coalesced"] == 1.0
    assert result["publication_current"] == 1.0


def test_mabm_ready_result_is_clamped_when_publication_is_expired(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    authority = FakeAuthority(
        FakeStatus(True, False, "accepted", now - timedelta(seconds=91), now - timedelta(seconds=1))
    )
    monkeypatch.setattr(v137, "_authority", lambda: authority)

    class FakeManager:
        def __init__(self) -> None:
            self._capital_coordinator = None
            self._capital_state_lock = FakeLock()
            self._capital_ready = True

        def refresh_capital_authority(self, trigger="manual"):
            return {"ready": 1.0, "total_capital": 468.02, "valid_brokers": 3.0}

    assert v137._patch_manager_class(FakeManager)
    manager = FakeManager()
    result = manager.refresh_capital_authority(trigger="watchdog")

    assert result["ready"] == 0.0
    assert result["publication_current"] == 0.0
    assert result["publication_fail_closed"] == 1.0
    assert manager._capital_ready is False


def test_deadline_refresh_uses_only_canonical_coordinator(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    snapshot = SimpleNamespace(
        real_capital=468.02,
        broker_count=1,
        broker_balances={"kraken": 468.02},
    )
    authority = FakeAuthority(
        FakeStatus(True, False, "accepted", now, now + timedelta(seconds=90)),
        snapshot=snapshot,
    )
    monkeypatch.setattr(v137, "_authority", lambda: authority)

    broker = SimpleNamespace(_last_known_balance=468.02)
    coordinator = FakeCoordinator(snapshot=snapshot)
    manager = _manager(coordinator)
    manager._platform_brokers = {"kraken": broker}

    assert v137._execute_deadline_refresh(manager, trigger="test_v137") is True
    assert len(coordinator.calls) == 1
    broker_map, trigger, exposure = coordinator.calls[0]
    assert broker_map == {"kraken": broker}
    assert trigger == "test_v137"
    assert exposure == 0.0
    assert manager._capital_ready is True
    assert manager._capital_last_valid_brokers == 1


def test_user_capital_remains_excluded_without_explicit_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("NIJA_AGGREGATE_USER_CAPITAL_IN_AUTHORITY", "false")
    platform_broker = SimpleNamespace(_last_known_balance=100.0)
    user_broker = SimpleNamespace(_last_known_balance=50.0, connected=True)
    manager = _manager()
    manager._platform_brokers = {"kraken": platform_broker}
    manager.user_brokers = {"tania": {"kraken": user_broker}}

    broker_map = v137._runtime_broker_map(manager)

    assert list(broker_map) == ["kraken"]
    assert user_broker not in broker_map.values()


def test_patch_does_not_change_nonce_risk_or_kill_switch_environment(monkeypatch) -> None:
    monkeypatch.setenv("NIJA_NONCE_READY", "1")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_EMERGENCY_STOP", "1")

    now = datetime.now(timezone.utc)
    authority = FakeAuthority(
        FakeStatus(True, False, "accepted", now, now + timedelta(seconds=80))
    )
    v137._publication_refresh_due(authority, _manager(), now=now)

    assert os.environ["NIJA_NONCE_READY"] == "1"
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EMERGENCY_STOP"] == "1"


def test_release_manifest_statically_wires_v137() -> None:
    from bot import runtime_release_manifest_patch as manifest

    assert manifest.RELEASE_ID == "20260817-runtime-convergence-v137"
    assert (
        "bot.capital_publication_deadline_v137_patch",
        "install_import_hook",
    ) in manifest._INSTALLERS
    assert manifest._REQUIRED_FLAGS["capital_publication_deadline_v137"] == (
        "NIJA_CAPITAL_PUBLICATION_DEADLINE_V137_INSTALLED"
    )
