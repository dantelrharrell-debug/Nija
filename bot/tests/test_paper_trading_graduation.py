"""
Test Suite for Paper Trading Graduation System
==============================================

Tests the graduation system, criteria evaluation, and mode transitions.
"""

import pytest
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

from bot.paper_trading_graduation import (
    PaperTradingGraduationSystem,
    TradingMode,
    GraduationStatus,
    GraduationProgress
)


@pytest.fixture
def test_data_dir(tmp_path):
    """Create temporary directory for test data"""
    data_dir = tmp_path / "graduation_test"
    data_dir.mkdir()
    return str(data_dir)


@pytest.fixture
def graduation_system(test_data_dir):
    """Create graduation system with test user"""
    return PaperTradingGraduationSystem("test_user_001", data_dir=test_data_dir)


class TestGraduationSystemInitialization:
    """Test initialization and data persistence"""

    def test_new_user_starts_in_paper_mode(self, graduation_system):
        """New users should start in paper trading mode"""
        assert graduation_system.progress.trading_mode == TradingMode.PAPER
        assert graduation_system.progress.status == GraduationStatus.NOT_ELIGIBLE
        assert graduation_system.progress.days_in_paper_trading == 0
        assert graduation_system.progress.total_paper_trades == 0

    def test_progress_persists_to_disk(self, graduation_system, test_data_dir):
        """Progress should be saved and loadable from disk"""
        # Update some data
        graduation_system.progress.total_paper_trades = 10
        graduation_system._save_progress()

        # Create new instance - should load saved data
        new_instance = PaperTradingGraduationSystem("test_user_001", data_dir=test_data_dir)
        assert new_instance.progress.total_paper_trades == 10


class TestCriteriaEvaluation:
    """Test graduation criteria evaluation"""

    def test_time_requirement_not_met(self, graduation_system):
        """User with less than 30 days should not meet time requirement"""
        paper_stats = {
            'total_trades': 25,
            'winning_trades': 15,
            'losing_trades': 10,
            'win_rate': 60.0,
            'total_pnl': 350.0,
            'max_drawdown': 12.5,
            'avg_position_size': 50.0
        }

        graduation_system.update_from_paper_account(paper_stats)

        assert "time_requirement" in graduation_system.progress.criteria_not_met
        assert not graduation_system.is_eligible_for_graduation()

    def test_time_requirement_met(self, graduation_system, test_data_dir):
        """User with 30+ days should meet time requirement"""
        # Manually set start date to 30 days ago
        past_date = (datetime.utcnow() - timedelta(days=30)).isoformat()
        graduation_system.progress.paper_trading_start_date = past_date

        paper_stats = {
            'total_trades': 25,
            'winning_trades': 15,
            'losing_trades': 10,
            'win_rate': 60.0,
            'total_pnl': 350.0,
            'max_drawdown': 12.5,
            'avg_position_size': 50.0
        }

        graduation_system.update_from_paper_account(paper_stats)

        assert "time_requirement" in graduation_system.progress.criteria_met

    def test_trade_volume_requirement(self, graduation_system):
        """User must have minimum 20 trades"""
        # Less than 20 trades
        paper_stats = {
            'total_trades': 15,
            'winning_trades': 10,
            'losing_trades': 5,
            'win_rate': 66.7,
            'total_pnl': 200.0,
            'max_drawdown': 10.0,
            'avg_position_size': 50.0
        }

        graduation_system.update_from_paper_account(paper_stats)
        assert "trade_volume" in graduation_system.progress.criteria_not_met

        # 20+ trades
        paper_stats['total_trades'] = 20
        graduation_system.update_from_paper_account(paper_stats)
        assert "trade_volume" in graduation_system.progress.criteria_met

    def test_win_rate_requirement(self, graduation_system):
        """User must have at least 40% win rate"""
        # Below 40%
        paper_stats = {
            'total_trades': 20,
            'winning_trades': 7,
            'losing_trades': 13,
            'win_rate': 35.0,
            'total_pnl': 100.0,
            'max_drawdown': 15.0,
            'avg_position_size': 50.0
        }

        graduation_system.update_from_paper_account(paper_stats)
        assert "win_rate" in graduation_system.progress.criteria_not_met

        # At or above 40%
        paper_stats['win_rate'] = 45.0
        graduation_system.update_from_paper_account(paper_stats)
        assert "win_rate" in graduation_system.progress.criteria_met

    def test_drawdown_control_requirement(self, graduation_system):
        """User must keep drawdown under 30%"""
        # Excessive drawdown
        paper_stats = {
            'total_trades': 20,
            'winning_trades': 10,
            'losing_trades': 10,
            'win_rate': 50.0,
            'total_pnl': 100.0,
            'max_drawdown': 35.0,
            'avg_position_size': 50.0
        }

        graduation_system.update_from_paper_account(paper_stats)
        assert "drawdown_control" in graduation_system.progress.criteria_not_met

        # Acceptable drawdown
        paper_stats['max_drawdown'] = 20.0
        graduation_system.update_from_paper_account(paper_stats)
        assert "drawdown_control" in graduation_system.progress.criteria_met


class TestRiskScoreCalculation:
    """Test risk score calculation algorithm"""

    def test_risk_score_excellent_performance(self, graduation_system):
        """Excellent performance should yield high risk score"""
        paper_stats = {
            'total_trades': 60,
            'winning_trades': 40,
            'losing_trades': 20,
            'win_rate': 66.7,
            'total_pnl': 800.0,
            'max_drawdown': 8.0,
            'avg_position_size': 50.0
        }

        graduation_system.update_from_paper_account(paper_stats)
        assert graduation_system.progress.risk_score >= 80

    def test_risk_score_poor_performance(self, graduation_system):
        """Poor performance should yield low risk score"""
        paper_stats = {
            'total_trades': 10,
            'winning_trades': 3,
            'losing_trades': 7,
            'win_rate': 30.0,
            'total_pnl': -50.0,
            'max_drawdown': 35.0,
            'avg_position_size': 50.0
        }

        graduation_system.update_from_paper_account(paper_stats)
        assert graduation_system.progress.risk_score < 50


class TestGraduationEligibility:
    """Test graduation eligibility determination"""

    def test_eligible_when_all_criteria_met(self, graduation_system):
        """User should be eligible when all criteria are met"""
        # Set start date to 30+ days ago
        past_date = (datetime.utcnow() - timedelta(days=35)).isoformat()
        graduation_system.progress.paper_trading_start_date = past_date

        # Excellent performance stats
        paper_stats = {
            'total_trades': 30,
            'winning_trades': 20,
            'losing_trades': 10,
            'win_rate': 66.7,
            'total_pnl': 500.0,
            'max_drawdown': 12.0,
            'avg_position_size': 50.0
        }

        graduation_system.update_from_paper_account(paper_stats)

        assert graduation_system.is_eligible_for_graduation()
        assert graduation_system.progress.status == GraduationStatus.ELIGIBLE

    def test_not_eligible_with_missing_criteria(self, graduation_system):
        """User should not be eligible if any criterion is missing"""
        paper_stats = {
            'total_trades': 15,  # Below minimum
            'winning_trades': 10,
            'losing_trades': 5,
            'win_rate': 66.7,
            'total_pnl': 500.0,
            'max_drawdown': 12.0,
            'avg_position_size': 50.0
        }

        graduation_system.update_from_paper_account(paper_stats)

        assert not graduation_system.is_eligible_for_graduation()


class TestGraduationProcess:
    """Test graduation to live trading"""

    def test_graduation_requires_eligibility(self, graduation_system):
        """Cannot graduate if not eligible"""
        result = graduation_system.graduate_to_live_trading()

        assert not result['success']
        assert 'does not meet' in result['message'].lower()

    def test_successful_graduation(self, graduation_system):
        """Eligible user can graduate to restricted live trading"""
        # Make user eligible
        past_date = (datetime.utcnow() - timedelta(days=35)).isoformat()
        graduation_system.progress.paper_trading_start_date = past_date

        paper_stats = {
            'total_trades': 30,
            'winning_trades': 20,
            'losing_trades': 10,
            'win_rate': 66.7,
            'total_pnl': 500.0,
            'max_drawdown': 12.0,
            'avg_position_size': 50.0
        }

        graduation_system.update_from_paper_account(paper_stats)

        # Graduate
        result = graduation_system.graduate_to_live_trading()

        assert result['success']
        assert graduation_system.progress.trading_mode == TradingMode.LIVE_RESTRICTED
        assert graduation_system.progress.graduation_date is not None

    def test_graduation_sets_restrictions(self, graduation_system):
        """Graduation should set appropriate capital restrictions"""
        # Make eligible and graduate
        past_date = (datetime.utcnow() - timedelta(days=35)).isoformat()
        graduation_system.progress.paper_trading_start_date = past_date

        paper_stats = {
            'total_trades': 30,
            'winning_trades': 20,
            'losing_trades': 10,
            'win_rate': 66.7,
            'total_pnl': 500.0,
            'max_drawdown': 12.0,
            'avg_position_size': 50.0
        }

        graduation_system.update_from_paper_account(paper_stats)
        result = graduation_system.graduate_to_live_trading()

        assert result['restrictions']['max_position_size'] == 100
        assert result['restrictions']['max_total_capital'] == 500


class TestFullAccessUnlock:
    """Test unlocking full live trading access"""

    def test_unlock_requires_restricted_mode_completion(self, graduation_system):
        """Cannot unlock full access without completing restricted period"""
        # Graduate to restricted
        graduation_system.progress.trading_mode = TradingMode.LIVE_RESTRICTED
        graduation_system.progress.live_trading_enabled_date = datetime.utcnow().isoformat()

        # Try to unlock immediately (should fail - need 14 days)
        result = graduation_system.unlock_full_live_trading()

        assert not result['success']
        assert 'days' in result['message'].lower()

    def test_successful_full_access_unlock(self, graduation_system):
        """Can unlock full access after 14 days in restricted mode"""
        # Graduate to restricted 14+ days ago
        graduation_system.progress.trading_mode = TradingMode.LIVE_RESTRICTED
        past_date = (datetime.utcnow() - timedelta(days=15)).isoformat()
        graduation_system.progress.live_trading_enabled_date = past_date

        # Unlock full access
        result = graduation_system.unlock_full_live_trading()

        assert result['success']
        assert graduation_system.progress.trading_mode == TradingMode.LIVE_FULL


class TestRevertToPaper:
    """Test reverting to paper trading"""

    def test_can_revert_from_any_mode(self, graduation_system):
        """User can revert to paper from any live mode"""
        # Test from restricted
        graduation_system.progress.trading_mode = TradingMode.LIVE_RESTRICTED
        result = graduation_system.revert_to_paper_trading()

        assert result['success']
        assert graduation_system.progress.trading_mode == TradingMode.PAPER

        # Test from full
        graduation_system.progress.trading_mode = TradingMode.LIVE_FULL
        result = graduation_system.revert_to_paper_trading()

        assert result['success']
        assert graduation_system.progress.trading_mode == TradingMode.PAPER


class TestTradingLimits:
    """Test trading limits based on mode"""

    def test_paper_mode_limits(self, graduation_system):
        """Paper mode should have no capital limits"""
        limits = graduation_system.get_current_limits()

        assert limits['mode'] == 'paper'
        assert limits['max_position_size'] is None
        assert limits['max_total_capital'] is None

    def test_restricted_mode_limits(self, graduation_system):
        """Restricted mode should have strict limits"""
        graduation_system.progress.trading_mode = TradingMode.LIVE_RESTRICTED
        limits = graduation_system.get_current_limits()

        assert limits['mode'] == 'live_restricted'
        assert limits['max_position_size'] == 100
        assert limits['max_total_capital'] == 500

    def test_full_mode_limits(self, graduation_system):
        """Full mode should have no platform limits"""
        graduation_system.progress.trading_mode = TradingMode.LIVE_FULL
        limits = graduation_system.get_current_limits()

        assert limits['mode'] == 'live_full'
        assert limits['max_position_size'] is None
        assert limits['max_total_capital'] is None


class TestCriteriaDetails:
    """Test detailed criteria breakdown"""

    def test_criteria_progress_tracking(self, graduation_system):
        """Criteria should track progress percentage"""
        paper_stats = {
            'total_trades': 15,  # 75% of 20 required
            'winning_trades': 9,
            'losing_trades': 6,
            'win_rate': 60.0,
            'total_pnl': 200.0,
            'max_drawdown': 15.0,
            'avg_position_size': 50.0
        }

        graduation_system.update_from_paper_account(paper_stats)
        criteria = graduation_system.get_criteria_details()

        # Find trade volume criterion
        trade_volume = next(c for c in criteria if c.criterion_id == 'trade_volume')
        assert trade_volume.progress == 75.0  # 15/20 = 75%

    def test_all_criteria_returned(self, graduation_system):
        """Should return all 5 graduation criteria"""
        criteria = graduation_system.get_criteria_details()

        assert len(criteria) == 5

        criterion_ids = [c.criterion_id for c in criteria]
        assert 'time_requirement' in criterion_ids
        assert 'trade_volume' in criterion_ids
        assert 'win_rate' in criterion_ids
        assert 'risk_management' in criterion_ids
        assert 'drawdown_control' in criterion_ids


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
