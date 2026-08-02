"""Tests for bot.dust_position_filter."""
from __future__ import annotations

import pytest

from bot.dust_position_filter import (
    DustFilterReport,
    DustPositionFilter,
    DustRecord,
    get_active_positions,
    is_dust_position,
)


# ---------------------------------------------------------------------------
# DustPositionFilter.is_dust
# ---------------------------------------------------------------------------

class TestIsDust:
    def test_below_threshold_is_dust(self):
        f = DustPositionFilter(dust_threshold_usd=1.0)
        assert f.is_dust("BTC-USD", 0.00000001, 50_000.0) is True

    def test_above_threshold_is_not_dust(self):
        f = DustPositionFilter(dust_threshold_usd=1.0)
        assert f.is_dust("BTC-USD", 1.0, 50_000.0) is False

    def test_zero_quantity_is_dust(self):
        f = DustPositionFilter(dust_threshold_usd=1.0)
        assert f.is_dust("ETH-USD", 0.0, 3000.0) is True

    def test_negative_quantity_is_dust(self):
        f = DustPositionFilter(dust_threshold_usd=1.0)
        assert f.is_dust("ETH-USD", -0.1, 3000.0) is True

    def test_exactly_at_threshold_is_not_dust(self):
        f = DustPositionFilter(dust_threshold_usd=1.0)
        # 0.00002 * 50000 = 1.0 — right at the boundary → not dust
        assert f.is_dust("BTC-USD", 0.00002, 50_000.0) is False


class TestIsDustPosition:
    def test_uses_qty_times_price(self):
        f = DustPositionFilter(dust_threshold_usd=1.0)
        pos = {"quantity": 0.00000001, "size_usd": 0.0}
        assert f.is_dust_position(pos, price_usd=50_000.0) is True

    def test_falls_back_to_snapshot_price(self):
        f = DustPositionFilter(dust_threshold_usd=1.0)
        pos = {"quantity": 0.00000001, "last_broker_snapshot_price": 50_000.0}
        assert f.is_dust_position(pos) is True

    def test_falls_back_to_size_usd(self):
        f = DustPositionFilter(dust_threshold_usd=1.0)
        pos = {"quantity": 0.001, "size_usd": 0.50}   # $0.50 → dust
        assert f.is_dust_position(pos) is True

    def test_non_dust_position(self):
        f = DustPositionFilter(dust_threshold_usd=1.0)
        pos = {"quantity": 0.1, "size_usd": 5000.0}
        assert f.is_dust_position(pos) is False


# ---------------------------------------------------------------------------
# DustPositionFilter.filter_for_execution
# ---------------------------------------------------------------------------

class TestFilterForExecution:
    def _positions(self):
        return {
            "BTC-USD": {"quantity": 1.0, "size_usd": 50_000.0},
            "DUST-USD": {"quantity": 0.00000001, "size_usd": 0.0005},
        }

    def test_dust_excluded_from_execution(self):
        f = DustPositionFilter(dust_threshold_usd=1.0)
        active = f.filter_for_execution(
            self._positions(), {"BTC-USD": 50_000.0, "DUST-USD": 50_000.0}
        )
        assert "BTC-USD" in active
        assert "DUST-USD" not in active

    def test_empty_positions(self):
        f = DustPositionFilter(dust_threshold_usd=1.0)
        assert f.filter_for_execution({}, {}) == {}


# ---------------------------------------------------------------------------
# DustPositionFilter.filter_for_reconciliation
# ---------------------------------------------------------------------------

class TestFilterForReconciliation:
    def test_dust_excluded_from_reconciliation(self):
        f = DustPositionFilter(dust_threshold_usd=1.0)
        positions = {
            "SOL-USD": {"quantity": 10.0, "size_usd": 1500.0},
            "TINY-USD": {"quantity": 1e-9, "size_usd": 0.0},
        }
        result = f.filter_for_reconciliation(positions, {"SOL-USD": 150.0, "TINY-USD": 1.0})
        assert "SOL-USD" in result
        assert "TINY-USD" not in result


# ---------------------------------------------------------------------------
# DustPositionFilter.get_dust_report
# ---------------------------------------------------------------------------

class TestGetDustReport:
    def test_counts_are_correct(self):
        f = DustPositionFilter(dust_threshold_usd=1.0, micro_threshold_usd=5.0)
        positions = {
            "BIG-USD":   {"quantity": 1.0, "size_usd": 1000.0},
            "DUST1-USD": {"quantity": 0.000001, "size_usd": 0.00005},
            "DUST2-USD": {"quantity": 0.000002, "size_usd": 0.0001},
        }
        prices = {"BIG-USD": 1000.0, "DUST1-USD": 50.0, "DUST2-USD": 50.0}
        report = f.get_dust_report(positions, prices)
        assert isinstance(report, DustFilterReport)
        assert report.total_positions == 3
        assert report.active_count == 1
        assert report.dust_count + report.micro_count == 2

    def test_includes_all_positions_in_report(self):
        f = DustPositionFilter(dust_threshold_usd=1.0)
        positions = {"A-USD": {"quantity": 0.0001, "size_usd": 0.005}}
        report = f.get_dust_report(positions, {"A-USD": 50.0})
        assert len(report.dust_positions) == 1
        assert report.dust_positions[0].symbol == "A-USD"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

class TestModuleFunctions:
    def test_is_dust_position_module_fn(self):
        assert is_dust_position("BTC-USD", 0.00000001, 50_000.0, threshold_usd=1.0) is True
        assert is_dust_position("ETH-USD", 1.0, 3000.0, threshold_usd=1.0) is False

    def test_get_active_positions_for_execution(self):
        positions = {
            "BTC-USD": {"quantity": 1.0, "size_usd": 50_000.0},
            "DUST-USD": {"quantity": 1e-9, "size_usd": 0.00005},
        }
        prices = {"BTC-USD": 50_000.0, "DUST-USD": 50_000.0}
        active = get_active_positions(positions, prices, for_reconciliation=False)
        assert "BTC-USD" in active
        assert "DUST-USD" not in active

    def test_get_active_positions_for_reconciliation(self):
        positions = {
            "SOL-USD": {"quantity": 10.0, "size_usd": 1500.0},
            "TINY-USD": {"quantity": 1e-9, "size_usd": 0.0},
        }
        prices = {"SOL-USD": 150.0, "TINY-USD": 1.0}
        active = get_active_positions(positions, prices, for_reconciliation=True)
        assert "SOL-USD" in active
        assert "TINY-USD" not in active

    def test_from_env_respects_env_var(self, monkeypatch):
        monkeypatch.setenv("NIJA_DUST_THRESHOLD_USD", "5.0")
        f = DustPositionFilter.from_env()
        assert f.dust_threshold_usd == pytest.approx(5.0)
