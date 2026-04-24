"""
Tests for bot/portfolio_kill_switch.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Allow imports from bot/
sys.path.insert(0, str(Path(__file__).parent.parent))

from portfolio_kill_switch import (
    PortfolioKillSwitch,
    PortfolioKillSwitchConfig,
    get_portfolio_kill_switch,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cfg_auto_disabled():
    """Config with auto-trigger disabled — for isolated unit tests."""
    return PortfolioKillSwitchConfig(
        drawdown_warning_pct=5.0,
        drawdown_halt_pct=15.0,
        consec_loss_warning=3,
        consec_loss_halt=6,
        daily_loss_halt_pct=5.0,
        auto_trigger_enabled=False,
    )


@pytest.fixture
def cfg_auto_enabled():
    """Config with auto-trigger enabled and tight thresholds for testing."""
    return PortfolioKillSwitchConfig(
        drawdown_warning_pct=2.0,
        drawdown_halt_pct=10.0,
        consec_loss_warning=2,
        consec_loss_halt=3,
        daily_loss_halt_pct=3.0,
        auto_trigger_enabled=True,
    )


@pytest.fixture
def pks_manual(cfg_auto_disabled, tmp_path):
    """Portfolio kill switch with auto-trigger disabled."""
    switch = PortfolioKillSwitch(cfg_auto_disabled)
    switch._state_file = tmp_path / "portfolio_kill_switch_state.json"
    return switch


@pytest.fixture
def pks_auto(cfg_auto_enabled, tmp_path):
    """Portfolio kill switch with auto-trigger enabled."""
    switch = PortfolioKillSwitch(cfg_auto_enabled)
    switch._state_file = tmp_path / "portfolio_kill_switch_state.json"
    return switch


# ---------------------------------------------------------------------------
# Basic trigger / reset
# ---------------------------------------------------------------------------


class TestManualTrigger:

    def test_initially_not_triggered(self, pks_manual):
        assert pks_manual.is_triggered() is False

    def test_trigger_sets_active(self, pks_manual):
        pks_manual.trigger("Test trigger", source="TEST")
        assert pks_manual.is_triggered() is True

    def test_trigger_records_reason(self, pks_manual):
        pks_manual.trigger("Suspicious activity", source="TEST")
        status = pks_manual.get_status()
        assert "Suspicious activity" in status["trigger_reason"]

    def test_trigger_records_timestamp(self, pks_manual):
        pks_manual.trigger("Test", source="TEST")
        status = pks_manual.get_status()
        assert status["trigger_timestamp"] is not None

    def test_trigger_is_idempotent(self, pks_manual):
        pks_manual.trigger("First trigger", source="TEST")
        pks_manual.trigger("Second trigger", source="TEST")
        status = pks_manual.get_status()
        # First reason is preserved
        assert "First trigger" in status["trigger_reason"]

    def test_reset_deactivates(self, pks_manual):
        pks_manual.trigger("Test", source="TEST")
        pks_manual.reset("Issue resolved", source="TEST")
        assert pks_manual.is_triggered() is False

    def test_reset_when_not_triggered_is_noop(self, pks_manual):
        # Should not raise
        pks_manual.reset("No-op reset")
        assert pks_manual.is_triggered() is False

    def test_history_records_trigger_and_reset(self, pks_manual):
        pks_manual.trigger("First", source="TEST")
        pks_manual.reset("Resolved", source="TEST")
        status = pks_manual.get_status()
        events = [e["event"] for e in status["recent_history"]]
        assert "trigger" in events
        assert "reset" in events


# ---------------------------------------------------------------------------
# Environment variable override
# ---------------------------------------------------------------------------


class TestEnvVarOverride:

    def test_env_var_1_triggers(self, pks_manual):
        with patch.dict("os.environ", {"NIJA_KILL_SWITCH": "1"}):
            assert pks_manual.is_triggered() is True

    def test_env_var_true_triggers(self, pks_manual):
        with patch.dict("os.environ", {"NIJA_KILL_SWITCH": "TRUE"}):
            assert pks_manual.is_triggered() is True

    def test_env_var_0_does_not_trigger(self, pks_manual):
        with patch.dict("os.environ", {"NIJA_KILL_SWITCH": "0"}):
            assert pks_manual.is_triggered() is False

    def test_no_env_var(self, pks_manual):
        with patch.dict("os.environ", {}, clear=True):
            # Remove NIJA_KILL_SWITCH if set
            env = dict(__import__("os").environ)
            env.pop("NIJA_KILL_SWITCH", None)
            with patch.dict("os.environ", env, clear=True):
                assert pks_manual.is_triggered() is False


# ---------------------------------------------------------------------------
# Auto-trigger: drawdown
# ---------------------------------------------------------------------------


class TestDrawdownAutoTrigger:

    def test_no_trigger_below_threshold(self, pks_auto):
        pks_auto.update_equity(100_000.0)
        # 5% drawdown < 10% drawdown halt, and 5% is also < 3% daily loss... wait:
        # 96% of 100k = 96000 → 4% daily loss > 3% daily halt, would trigger.
        # Use a 1% drop: stays below both drawdown halt (10%) and daily loss halt (3%).
        pks_auto.update_equity(99_000.0)   # 1% drawdown, 1% daily loss — both below thresholds
        assert pks_auto.is_triggered() is False

    def test_trigger_at_halt_threshold(self, pks_auto):
        pks_auto.update_equity(100_000.0)   # peak
        pks_auto.update_equity(90_000.0)    # 10% drawdown = halt threshold
        assert pks_auto.is_triggered() is True

    def test_trigger_above_halt_threshold(self, pks_auto):
        pks_auto.update_equity(100_000.0)
        pks_auto.update_equity(80_000.0)    # 20% drawdown
        assert pks_auto.is_triggered() is True

    def test_peak_updated_on_new_high(self, pks_auto):
        pks_auto.update_equity(100_000.0)
        pks_auto.update_equity(120_000.0)  # new peak
        # 10% drop from new peak
        pks_auto.update_equity(108_000.0)  # only 10% from 120k → exactly halt
        assert pks_auto.is_triggered() is True

    def test_no_trigger_when_auto_disabled(self, pks_manual):
        # pks_manual has auto_trigger_enabled=False
        pks_manual.update_equity(100_000.0)
        pks_manual.update_equity(50_000.0)   # would trigger if enabled
        assert pks_manual.is_triggered() is False

    def test_trigger_reason_mentions_drawdown(self, pks_auto):
        pks_auto.update_equity(100_000.0)
        pks_auto.update_equity(85_000.0)
        status = pks_auto.get_status()
        assert "drawdown" in status["trigger_reason"].lower()


# ---------------------------------------------------------------------------
# Auto-trigger: daily loss
# ---------------------------------------------------------------------------


class TestDailyLossAutoTrigger:

    def test_no_trigger_below_threshold(self, pks_auto):
        pks_auto.update_equity(100_000.0)   # sets day-start
        pks_auto.update_equity(98_000.0)    # 2% loss < 3% halt
        assert pks_auto.is_triggered() is False

    def test_trigger_at_daily_loss_threshold(self, pks_auto):
        pks_auto.update_equity(100_000.0)   # sets day-start
        pks_auto.update_equity(97_000.0)    # exactly 3% loss
        assert pks_auto.is_triggered() is True

    def test_trigger_reason_mentions_daily_loss(self, pks_auto):
        pks_auto.update_equity(100_000.0)
        pks_auto.update_equity(96_000.0)
        status = pks_auto.get_status()
        assert "daily loss" in status["trigger_reason"].lower()


# ---------------------------------------------------------------------------
# Auto-trigger: consecutive losses
# ---------------------------------------------------------------------------


class TestConsecutiveLossAutoTrigger:

    def test_no_trigger_below_threshold(self, pks_auto):
        # halt at 3 losses
        pks_auto.record_trade_result(is_winner=False)
        pks_auto.record_trade_result(is_winner=False)
        assert pks_auto.is_triggered() is False

    def test_trigger_at_halt_threshold(self, pks_auto):
        for _ in range(3):
            pks_auto.record_trade_result(is_winner=False)
        assert pks_auto.is_triggered() is True

    def test_win_resets_counter(self, pks_auto):
        pks_auto.record_trade_result(is_winner=False)
        pks_auto.record_trade_result(is_winner=False)
        pks_auto.record_trade_result(is_winner=True)   # resets
        # Need 3 more losses to trigger
        pks_auto.record_trade_result(is_winner=False)
        pks_auto.record_trade_result(is_winner=False)
        assert pks_auto.is_triggered() is False

    def test_trigger_reason_mentions_consecutive(self, pks_auto):
        for _ in range(3):
            pks_auto.record_trade_result(is_winner=False)
        status = pks_auto.get_status()
        assert "consecutive" in status["trigger_reason"].lower()

    def test_no_trigger_when_auto_disabled(self, pks_manual):
        for _ in range(10):
            pks_manual.record_trade_result(is_winner=False)
        assert pks_manual.is_triggered() is False


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------


class TestStatePersistence:

    def test_state_persisted_on_trigger(self, pks_manual, tmp_path):
        state_file = tmp_path / "portfolio_kill_switch_state.json"
        pks_manual._state_file = state_file
        pks_manual.trigger("Persist test", source="TEST")
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["triggered"] is True
        assert "Persist test" in data["trigger_reason"]

    def test_state_persisted_on_reset(self, pks_manual, tmp_path):
        state_file = tmp_path / "portfolio_kill_switch_state.json"
        pks_manual._state_file = state_file
        pks_manual.trigger("Test", source="TEST")
        pks_manual.reset("Resolved", source="TEST")
        data = json.loads(state_file.read_text())
        assert data["triggered"] is False

    def test_state_loaded_on_init(self, cfg_auto_disabled, tmp_path):
        state_file = tmp_path / "portfolio_kill_switch_state.json"
        state_file.write_text(
            json.dumps({
                "triggered": True,
                "trigger_reason": "Previous session trigger",
                "trigger_timestamp": "2026-01-01T00:00:00+00:00",
                "history": [],
            })
        )
        switch = PortfolioKillSwitch(cfg_auto_disabled)
        switch._state_file = state_file
        switch._load_state()
        assert switch._triggered is True


# ---------------------------------------------------------------------------
# KillSwitch propagation
# ---------------------------------------------------------------------------


class TestKillSwitchPropagation:

    def test_propagates_to_kill_switch(self, pks_manual):
        mock_ks = MagicMock()
        mock_factory = MagicMock(return_value=mock_ks)

        with patch("portfolio_kill_switch.PortfolioKillSwitch._propagate_to_kill_switch") as mock_prop:
            pks_manual.trigger("Propagation test", source="TEST")
            mock_prop.assert_called_once()
            args = mock_prop.call_args[0]
            assert "Propagation test" in args[0]


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:

    def test_status_keys(self, pks_manual):
        status = pks_manual.get_status()
        expected_keys = {
            "triggered",
            "trigger_reason",
            "trigger_timestamp",
            "peak_equity",
            "current_equity",
            "consecutive_losses",
            "auto_trigger_enabled",
            "recent_history",
        }
        assert expected_keys.issubset(status.keys())

    def test_status_reflects_trigger(self, pks_manual):
        pks_manual.trigger("Status test", source="TEST")
        status = pks_manual.get_status()
        assert status["triggered"] is True
