"""Regression tests: v449 telemetry cannot grant trading authority."""
from bot.execution_preflight_observability_v449 import PREFLIGHT_KEYS, observe_preflight


def _all_ready():
    return {key: True for key in PREFLIGHT_KEYS}


def _observe(readiness, **overrides):
    values = dict(
        kill_switch_clear=True,
        ledger_verified=True,
        protective_exits_verified=True,
        broker_permissions_verified=True,
        broker_data_fresh=True,
    )
    values.update(overrides)
    return observe_preflight(readiness, **values)


def test_healthy_preflight_is_only_observational():
    result = _observe(_all_ready())
    assert result["preflight_operational_ready_observed"] is True
    assert result["diagnostic_only"] is True
    assert result["execution_authority_granted"] is False
    assert result["last_execution_evidence_status"] == "unverified"


def test_missing_verified_ledger_remains_unready():
    result = _observe(_all_ready(), ledger_verified=False)
    assert result["preflight_operational_ready_observed"] is False
    assert "ledger_verified" in result["preflight_missing"]
    assert result["execution_authority_granted"] is False


def test_active_kill_switch_or_missing_exits_fails_closed():
    for parameter in ("kill_switch_clear", "protective_exits_verified"):
        result = _observe(_all_ready(), **{parameter: False})
        assert not result["preflight_operational_ready_observed"]
        assert parameter in result["preflight_missing"]


def test_stale_execution_evidence_does_not_change_preflight_result():
    result = _observe(
        _all_ready(),
        last_execution_evidence={"verified": True, "fresh": False},
    )
    assert result["last_execution_evidence_status"] == "stale"
    assert result["execution_authority_granted"] is False


def test_missing_broker_freshness_blocks_observed_preflight():
    result = _observe(_all_ready(), broker_data_fresh=False)
    assert "broker_data_fresh" in result["preflight_missing"]
    assert result["preflight_operational_ready_observed"] is False


def test_omitted_readiness_keys_default_false():
    result = _observe({})
    assert not result["preflight_operational_ready_observed"]
    assert set(PREFLIGHT_KEYS).issubset(result["preflight_missing"])
