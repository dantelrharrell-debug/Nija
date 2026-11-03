from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from bot.kraken_production_source_diagnostics_v494 import (
    inspect_kraken_production_sources,
)


ACCOUNT = "platform:kraken"
NOW = 1_800_000_000.0
FIELDS = (
    "position_ledger_reconciliation",
    "duplicate_order_fence",
    "operator_authorization",
    "kill_switch_clear",
    "risk_limits",
    "position_sync",
)


class FakeRedis:
    def __init__(self, value=None, *, ping=True):
        self.value = value
        self.ping_result = ping

    def ping(self):
        return self.ping_result

    def get(self, _key):
        return self.value


class FakeKillSwitch:
    DURABLE_REDIS_KEY = "nija:global:kill_switch:v1"

    def __init__(self, *, active=False, file_exists=False):
        self.active = active
        self.file_exists = file_exists

    def get_status(self):
        return {
            "is_active": self.active,
            "kill_file_exists": self.file_exists,
        }

    def is_active(self):
        return self.active


class FakeRiskGovernor:
    def get_status(self):
        return {
            "halt_active": False,
            "halt_reason": "none",
            "config": {
                "max_daily_loss_pct": 5.0,
                "max_consecutive_losses": 5,
                "max_open_positions": 12,
                "max_total_risk_pct": 25.0,
            },
            "open_positions": 0,
            "consecutive_losses": 0,
        }


def _arguments(tmp_path, **updates):
    root = tmp_path / "persistent"
    root.mkdir(parents=True)
    ledger = root / "trade_ledger.db"
    with sqlite3.connect(ledger) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER)")
    values = {
        "account_scope": ACCOUNT,
        "ledger_path": ledger,
        "persistent_root": root,
        "now_epoch": NOW,
    }
    values.update(updates)
    return values


def _identity(account=ACCOUNT, observed_at=NOW):
    return {
        "account": account,
        "source": "authenticated_broker",
        "provider_id": "reviewed-kraken-identity",
        "evidence_id": "identity-read-1",
        "verified": True,
        "read_only": True,
        "scope_verified": True,
        "observed_at_epoch": observed_at,
        "provenance": {
            "account_scope_verified": True,
            "collector_identity_verified": True,
            "snapshot_complete": True,
            "authenticated_broker_read_verified": True,
            "complete_pagination_verified": True,
        },
    }


def test_six_sources_remain_fail_closed_when_approval_and_complete_sources_are_missing(tmp_path):
    report = inspect_kraken_production_sources(**_arguments(tmp_path))

    assert tuple(report["checks"]) == FIELDS
    assert not report["all_six_ready"]
    assert report["checks"]["position_ledger_reconciliation"] is False
    assert report["checks"]["duplicate_order_fence"] is False
    assert report["checks"]["operator_authorization"] is False
    assert report["checks"]["kill_switch_clear"] is False
    assert report["checks"]["risk_limits"] is False
    assert report["checks"]["position_sync"] is False
    assert report["sources"]["operator_authorization"]["reason"] == (
        "general_live_order_authorization_source_missing"
    )
    assert report["sources"]["duplicate_order_fence"]["reason"] == (
        "shared_redis_unavailable"
    )
    assert report["authorizes_orders"] is False
    assert report["collector_registration_attempted"] is False


def test_absent_durable_clearance_is_not_independent_evidence(tmp_path, monkeypatch):
    monkeypatch.delenv("NIJA_KILL_SWITCH", raising=False)
    redis = FakeRedis()
    kill_switch = FakeKillSwitch()

    # The real is_active() may persist a filesystem-triggered kill-switch
    # activation. A diagnostic must not call it, even when Redis is empty.
    def must_not_call():
        raise AssertionError("side-effecting kill switch check invoked")

    kill_switch.is_active = must_not_call
    report = inspect_kraken_production_sources(
        **_arguments(
            tmp_path, redis_client=redis, kill_switch=kill_switch,
        )
    )

    assert report["checks"]["kill_switch_clear"] is False
    assert report["sources"]["kill_switch_clear"]["reason"] == (
        "explicit_durable_clearance_record_missing"
    )
    assert report["authorizes_orders"] is False
    assert report["collector_registration_attempted"] is False
    assert report["execution_authority_changed"] is False


def test_explicit_clearance_is_diagnostic_not_an_approval(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.delenv("NIJA_KILL_SWITCH", raising=False)
    clearing = json.dumps({
        "schema": 2, "is_active": False, "reason": "synthetic-only",
        "timestamp": datetime.fromtimestamp(NOW - 10, timezone.utc).isoformat(),
    })
    redis = FakeRedis(clearing)
    switch = FakeKillSwitch()
    switch.is_active = lambda: (_ for _ in ()).throw(
        AssertionError("side-effecting is_active called")
    )
    report = inspect_kraken_production_sources(
        **_arguments(
            tmp_path, redis_client=redis, kill_switch=switch,
        )
    )
    assert report["checks"]["kill_switch_clear"] is False
    source = report["sources"]["kill_switch_clear"]
    assert source["reason"] == "independent_durable_clearance_binding_required"
    assert source["explicit_clearance_record_observed"] is True
    assert source["independent_clearance_approved"] is False
    assert report["authorizes_orders"] is False


def test_malformed_or_duplicate_durable_state_never_certifies(tmp_path, monkeypatch):
    monkeypatch.delenv("NIJA_KILL_SWITCH", raising=False)
    for index, value in enumerate((
        "not-json",
        '{"is_active":false,"is_active":false,"schema":2}',
        '{"is_active":false,"schema":99,"reason":"bad","timestamp":"2026-01-01T00:00:00+00:00"}',
        '{"is_active":null}',
    )):
        report = inspect_kraken_production_sources(
            **_arguments(
                tmp_path / str(index), redis_client=FakeRedis(value),
                kill_switch=FakeKillSwitch(),
            )
        )
        assert report["checks"]["kill_switch_clear"] is False
        assert report["sources"]["kill_switch_clear"]["reason"] == (
            "durable_kill_switch_record_unverified"
        )
        assert report["authorizes_orders"] is False


def test_active_contradictory_or_unavailable_shared_kill_state_fails_closed(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv("NIJA_KILL_SWITCH", raising=False)
    cases = (
        (FakeRedis(json.dumps({"is_active": True})), FakeKillSwitch(), "durable_kill_switch_active"),
        (FakeRedis(), FakeKillSwitch(active=True), "local_and_shared_kill_switch_state_not_proven_clear"),
        (FakeRedis(ping=False), FakeKillSwitch(), "shared_redis_ping_unverified"),
    )
    for index, (redis, kill_switch, reason) in enumerate(cases):
        report = inspect_kraken_production_sources(
            **_arguments(
                tmp_path / str(index),
                redis_client=redis,
                kill_switch=kill_switch,
            )
        )
        assert report["checks"]["kill_switch_clear"] is False
        assert report["sources"]["kill_switch_clear"]["reason"] == reason


def test_redis_health_does_not_certify_duplicate_order_fence(tmp_path):
    redis = FakeRedis()
    registry = SimpleNamespace(_redis=redis)
    report = inspect_kraken_production_sources(
        **_arguments(
            tmp_path, redis_client=redis, idempotency_registry=registry,
        )
    )

    assert report["checks"]["duplicate_order_fence"] is False
    assert report["sources"]["duplicate_order_fence"]["shared_redis_verified"] is True
    assert report["sources"]["duplicate_order_fence"]["registry_local_cache_not_used"] is True


def test_healthy_global_governor_does_not_certify_account_scoped_risk(tmp_path):
    report = inspect_kraken_production_sources(
        **_arguments(tmp_path, risk_governor=FakeRiskGovernor())
    )

    assert report["checks"]["risk_limits"] is False
    assert report["sources"]["risk_limits"]["existing_governor_snapshot_healthy"] is True
    assert report["sources"]["risk_limits"]["independent_certification"] is False


def test_fresh_authenticated_position_snapshot_can_be_diagnosed_without_authority(
    tmp_path, monkeypatch,
):
    from bot import runtime_authoritative_position_coverage_v285_patch as positions

    broker = SimpleNamespace(
        broker_type="kraken",
        account_type="platform",
        user_id=None,
        _nija_authoritative_position_snapshot_at_wall_v285=NOW,
        _startup_position_sync_fetch_ok=True,
        _startup_position_sync_adopted=True,
    )
    monkeypatch.setattr(positions, "_snapshot_status", lambda _broker: (
        True, "authoritative_position_snapshot_current", (), 0.0, 4,
    ))
    monkeypatch.setattr(positions, "_strong_broker_proof", lambda _broker: (
        True, "authoritative_current_position_snapshot_adopted",
    ))
    monkeypatch.setattr(positions, "_snapshot_max_age_s", lambda: 90.0)
    report = inspect_kraken_production_sources(
        **_arguments(
            tmp_path,
            broker=broker,
            identity_provider=lambda: _identity(),
        )
    )

    assert report["checks"]["position_sync"] is False
    assert report["sources"]["position_sync"]["snapshot_verified"] is True
    assert report["sources"]["position_sync"]["ledger_consistency_verified"] is False
    assert report["sources"]["position_sync"]["reason"] == (
        "reconciled_ledger_unavailable_for_position_comparison"
    )
    assert report["sources"]["position_sync"]["snapshot_generation"] == 4
    assert report["sources"]["position_sync"]["account_scope"] == ACCOUNT
    assert report["authorizes_orders"] is False


def test_position_sync_rejects_account_mismatch_and_stale_wall_clock(tmp_path, monkeypatch):
    from bot import runtime_authoritative_position_coverage_v285_patch as positions

    monkeypatch.setattr(positions, "_snapshot_status", lambda _broker: (
        True, "authoritative_position_snapshot_current", (), 0.0, 4,
    ))
    monkeypatch.setattr(positions, "_strong_broker_proof", lambda _broker: (
        True, "authoritative_current_position_snapshot_adopted",
    ))
    monkeypatch.setattr(positions, "_snapshot_max_age_s", lambda: 90.0)

    broker = SimpleNamespace(
        broker_type="kraken",
        account_type="platform",
        user_id=None,
        _nija_authoritative_position_snapshot_at_wall_v285=NOW - 91,
        _startup_position_sync_fetch_ok=True,
        _startup_position_sync_adopted=True,
    )
    mismatch = inspect_kraken_production_sources(
        **_arguments(
            tmp_path / "mismatch",
            broker=broker,
            identity_provider=lambda: _identity(account="platform:coinbase"),
        )
    )
    stale = inspect_kraken_production_sources(
        **_arguments(
            tmp_path / "stale",
            broker=broker,
            identity_provider=lambda: _identity(),
        )
    )

    assert mismatch["sources"]["position_sync"]["reason"] == (
        "authenticated_account_identity_unverified"
    )
    assert stale["sources"]["position_sync"]["reason"] == (
        "authoritative_snapshot_wall_clock_stale_or_invalid"
    )


def test_invalid_scope_and_clock_are_rejected(tmp_path):
    args = _arguments(tmp_path)
    args["account_scope"] = "platform:coinbase"
    try:
        inspect_kraken_production_sources(**args)
    except ValueError as exc:
        assert str(exc) == "platform_kraken_scope_required"
    else:
        raise AssertionError("non-Kraken account scope was accepted")

    args = _arguments(tmp_path / "clock")
    args["now_epoch"] = float("nan")
    try:
        inspect_kraken_production_sources(**args)
    except ValueError as exc:
        assert str(exc) == "diagnostic_clock_invalid"
    else:
        raise AssertionError("invalid clock was accepted")
