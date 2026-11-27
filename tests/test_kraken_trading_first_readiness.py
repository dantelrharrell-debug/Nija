"""Offline safety regressions for the trading-first readiness projection."""
from bot.kraken_trading_first_readiness import CRITICAL, Evidence, Mode, evaluate


def snapshot(**overrides):
    data = dict(
        protected_source_verified=True,
        collector_installed=True,
        current_observations={key: True for key in CRITICAL},
        broker_ledger_reconciled=True,
        release_security_verified=True,
        required_receipts_verified=True,
        bounded_operator_authorization=True,
        canonical_execution_gate_allows=True,
    )
    data.update(overrides)
    return Evidence(**data)


def test_all_verified_is_diagnostic_not_authorization():
    result = evaluate(snapshot())
    assert result.mode is Mode.LIMITED_LIVE_OBSERVED
    assert result.diagnostic_only and not result.authorizes_orders


def test_reporting_outage_does_not_block():
    assert evaluate(snapshot(noncritical_reporting_available=False)).mode is Mode.LIMITED_LIVE_OBSERVED


def test_missing_collector_denies():
    result = evaluate(snapshot(collector_installed=False))
    assert result.mode is Mode.RECOVERY
    assert "collector_missing" in result.blockers


def test_each_missing_critical_observation_denies():
    for missing in CRITICAL:
        result = evaluate(snapshot(current_observations={
            key: key != missing for key in CRITICAL
        }))
        assert result.mode is Mode.VERIFYING
        assert result.verified_count == 12
        assert not result.authorizes_orders


def test_unreconciled_or_unverified_receipt_denies():
    assert evaluate(snapshot(broker_ledger_reconciled=False)).mode is Mode.VERIFYING
    assert evaluate(snapshot(required_receipts_verified=False)).mode is Mode.VERIFYING


def test_operator_authorization_and_canonical_gate_remain_mandatory():
    assert evaluate(snapshot(bounded_operator_authorization=False)).mode is Mode.LIVE_ELIGIBLE
    assert evaluate(snapshot(canonical_execution_gate_allows=False)).mode is Mode.LIVE_ELIGIBLE


def test_integrity_failure_forces_protective_stop():
    assert evaluate(snapshot(material_integrity_failure=True)).mode is Mode.PROTECTIVE_STOP
