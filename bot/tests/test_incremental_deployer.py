"""
Tests for bot/incremental_deployer.py
"""

import sys
import json
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from incremental_deployer import (
    IncrementalDeployer,
    DeployPhase,
    LiveTradeAudit,
    PhaseStats,
    MIN_TRADES_PER_PHASE,
)


@pytest.fixture
def deployer(tmp_path):
    """Fresh IncrementalDeployer backed by a temp directory."""
    return IncrementalDeployer(
        total_risk_budget=10_000.0,
        data_path=str(tmp_path / "deployer_state.json"),
    )


class TestDeployPhase:
    def test_paper_capital_fraction_zero(self):
        assert DeployPhase.PAPER.capital_fraction == 0.0

    def test_micro_capital_fraction(self):
        assert DeployPhase.MICRO.capital_fraction == pytest.approx(0.01)

    def test_full_capital_fraction(self):
        assert DeployPhase.FULL.capital_fraction == pytest.approx(0.40)

    def test_next_phase_from_paper(self):
        assert DeployPhase.PAPER.next_phase() == DeployPhase.MICRO

    def test_next_phase_from_full_is_none(self):
        assert DeployPhase.FULL.next_phase() is None


class TestIncrementalDeployer:
    def test_starts_in_paper_phase(self, deployer):
        assert deployer.current_phase == DeployPhase.PAPER

    def test_paper_phase_live_capital_is_zero(self, deployer):
        assert deployer.get_live_capital() == pytest.approx(0.0)

    def test_position_size_scaled_to_zero_in_paper(self, deployer):
        assert deployer.get_position_size_usd(1000.0) == pytest.approx(0.0)

    def test_record_trade_returns_audit(self, deployer):
        audit = deployer.record_trade(
            trade_id="T001", symbol="BTC-USD", side="buy",
            size_usd=500, entry_price=50_000, exit_price=51_000,
            pnl_usd=10, strategy="ApexTrend", venue="coinbase",
        )
        assert isinstance(audit, LiveTradeAudit)
        assert audit.trade_id == "T001"

    def test_record_trade_updates_total_count(self, deployer):
        deployer.record_trade(
            "T001", "ETH-USD", "buy", 200, 3000, 3100, 20, "MomentumBreakout", "kraken"
        )
        status = deployer.status()
        assert status["total_live_trades"] == 1

    def test_can_advance_false_initially(self, deployer):
        ok, reason = deployer.can_advance()
        assert ok is False
        assert "trades" in reason

    def test_kill_switch_resets_to_paper(self, deployer, tmp_path):
        # Manually advance to MICRO
        deployer._state.current_phase = DeployPhase.MICRO.value
        deployer.activate_kill_switch("Test kill switch")
        assert deployer.current_phase == DeployPhase.PAPER

    def test_deactivate_kill_switch(self, deployer):
        deployer.activate_kill_switch("Test")
        deployer.deactivate_kill_switch()
        assert deployer._state.kill_switch_active is False

    def test_status_returns_dict(self, deployer):
        status = deployer.status()
        assert "current_phase" in status
        assert "capital_fraction" in status
        assert "live_capital_usd" in status
        assert "total_live_trades" in status

    def test_state_persists(self, tmp_path):
        path = str(tmp_path / "state.json")
        d1 = IncrementalDeployer(total_risk_budget=5000, data_path=path)
        d1.record_trade("T1", "BTC-USD", "buy", 100, 50000, 50100, 10, "A", "coinbase")

        # Re-load from disk
        d2 = IncrementalDeployer(total_risk_budget=5000, data_path=path)
        assert d2.status()["total_live_trades"] == 1

    def test_ledger_file_written(self, tmp_path):
        path = str(tmp_path / "state.json")
        d = IncrementalDeployer(data_path=path)
        d.record_trade("T1", "BTC-USD", "buy", 100, 50000, 50500, 50, "A", "coinbase")
        ledger = tmp_path / "trade_ledger.jsonl"
        assert ledger.exists()
        line = json.loads(ledger.read_text().strip())
        assert line["trade_id"] == "T1"

    def test_auto_advance_after_sufficient_winning_trades(self, tmp_path):
        """Meeting PAPER→MICRO criteria should advance the phase."""
        path = str(tmp_path / "advance_state.json")
        d = IncrementalDeployer(total_risk_budget=10_000, data_path=path)

        # Patch phase to PAPER and criteria
        # PAPER phase has no advance criteria row; use MICRO for test
        d._state.current_phase = DeployPhase.MICRO.value
        min_trades = MIN_TRADES_PER_PHASE["MICRO"]   # 20

        for i in range(min_trades):
            d.record_trade(
                f"T{i}", "BTC-USD", "buy", 100,
                50000, 51000, 50, "ApexTrend", "coinbase",
            )

        # After enough winning trades, should advance to SMALL
        assert d.current_phase == DeployPhase.SMALL
