"""
Tests for bot/alert_manager.py
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from alert_manager import (
    AlertManager,
    Alert,
    AlertSeverity,
    AlertCategory,
    get_alert_manager,
)


@pytest.fixture
def manager(tmp_path):
    """Fresh AlertManager with temp log dir for each test."""
    return AlertManager(
        log_dir=str(tmp_path / "alerts"),
        cooldown_seconds=0,          # no cooldown in tests
        pause_duration_seconds=60,
        auto_pause_on_critical=True,
    )


class TestAlertFiring:
    def test_fire_returns_alert(self, manager):
        alert = manager.fire(
            severity=AlertSeverity.INFO,
            category=AlertCategory.SYSTEM,
            title="Test",
            message="Test message",
        )
        assert isinstance(alert, Alert)
        assert alert.alert_id.startswith("ALERT-")

    def test_alert_stored(self, manager):
        manager.fire(AlertSeverity.WARNING, AlertCategory.SYSTEM, "T", "M")
        assert len(manager.get_recent_alerts()) == 1

    def test_cooldown_suppresses_second_fire(self):
        mgr = AlertManager(
            log_dir="",
            cooldown_seconds=3600,
            pause_duration_seconds=60,
        )
        a1 = mgr.fire(
            AlertSeverity.WARNING, AlertCategory.SYSTEM, "T", "M",
            cooldown_key="test_key",
        )
        a2 = mgr.fire(
            AlertSeverity.WARNING, AlertCategory.SYSTEM, "T", "M",
            cooldown_key="test_key",
        )
        assert a1 is not None
        assert a2 is None  # suppressed by cooldown

    def test_strategy_performance_deviation_fires(self, manager):
        alert = manager.strategy_performance_deviation(
            strategy="ApexTrend", metric="win_rate",
            current_value=0.30, threshold=0.48,
        )
        assert alert is not None
        assert alert.category == AlertCategory.STRATEGY_PERFORMANCE

    def test_execution_anomaly_fires(self, manager):
        alert = manager.execution_anomaly(
            venue="coinbase", symbol="BTC-USD",
            anomaly_type="high_slippage", detail="50 bps slippage",
        )
        assert alert is not None
        assert alert.category == AlertCategory.EXECUTION_ANOMALY

    def test_compliance_violation_fires(self, manager):
        alert = manager.compliance_violation(rule="KYC_CHECK", detail="Blocked trade")
        assert alert is not None
        assert alert.category == AlertCategory.COMPLIANCE_VIOLATION

    def test_risk_limit_breach_fires(self, manager):
        alert = manager.risk_limit_breach(
            limit_type="VaR-99", current_value=0.12, limit_value=0.08
        )
        assert alert is not None
        assert alert.category == AlertCategory.RISK_LIMIT_BREACH


class TestAutoPause:
    def test_critical_alert_triggers_pause(self, manager):
        assert manager.is_paused() is False
        manager.fire(AlertSeverity.CRITICAL, AlertCategory.SYSTEM, "Critical!", "Now")
        assert manager.is_paused() is True

    def test_emergency_alert_triggers_pause(self, manager):
        manager.fire(AlertSeverity.EMERGENCY, AlertCategory.RISK_LIMIT_BREACH, "Emergency", "!")
        assert manager.is_paused() is True

    def test_info_alert_does_not_trigger_pause(self, manager):
        manager.fire(AlertSeverity.INFO, AlertCategory.SYSTEM, "Info", "ok")
        assert manager.is_paused() is False

    def test_resume_lifts_pause(self, manager):
        manager.fire(AlertSeverity.CRITICAL, AlertCategory.SYSTEM, "Crit", "X")
        assert manager.is_paused() is True
        manager.resume()
        assert manager.is_paused() is False

    def test_pause_status_returns_dict(self, manager):
        status = manager.pause_status()
        assert "paused" in status
        assert "reason" in status


class TestHandlers:
    def test_webhook_handler_called(self, manager):
        handler = MagicMock()
        manager.add_webhook_handler(handler)
        manager.fire(AlertSeverity.INFO, AlertCategory.SYSTEM, "T", "M")
        handler.assert_called_once()
        assert isinstance(handler.call_args[0][0], Alert)

    def test_email_handler_called(self, manager):
        handler = MagicMock()
        manager.add_email_handler(handler)
        manager.fire(AlertSeverity.INFO, AlertCategory.SYSTEM, "T", "M")
        handler.assert_called_once()


class TestQueries:
    def test_filter_by_severity(self, manager):
        manager.fire(AlertSeverity.INFO, AlertCategory.SYSTEM, "I", "i")
        manager.fire(AlertSeverity.WARNING, AlertCategory.SYSTEM, "W", "w")
        warnings = manager.get_recent_alerts(severity=AlertSeverity.WARNING)
        assert len(warnings) == 1
        assert warnings[0].severity == AlertSeverity.WARNING

    def test_filter_by_category(self, manager):
        manager.fire(AlertSeverity.INFO, AlertCategory.SYSTEM, "S", "s")
        manager.fire(AlertSeverity.INFO, AlertCategory.EXECUTION_ANOMALY, "E", "e")
        exec_alerts = manager.get_recent_alerts(category=AlertCategory.EXECUTION_ANOMALY)
        assert len(exec_alerts) == 1

    def test_acknowledge(self, manager):
        alert = manager.fire(AlertSeverity.INFO, AlertCategory.SYSTEM, "T", "M")
        assert manager.unacknowledged_count() == 1
        found = manager.acknowledge(alert.alert_id)
        assert found is True
        assert manager.unacknowledged_count() == 0

    def test_acknowledge_unknown_id_returns_false(self, manager):
        found = manager.acknowledge("ALERT-INVALID")
        assert found is False

    def test_singleton(self):
        a = get_alert_manager()
        b = get_alert_manager()
        assert a is b
