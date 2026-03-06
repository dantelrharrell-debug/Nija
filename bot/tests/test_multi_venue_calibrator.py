"""
Tests for bot/multi_venue_calibrator.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from multi_venue_calibrator import (
    ExecutionSample,
    MultiVenueCalibrator,
    VenueStats,
    RoutingRecommendation,
    get_multi_venue_calibrator,
    SLIPPAGE_WARN_BPS,
    FILL_RATE_WARN,
)


def _make_sample(
    venue="coinbase",
    symbol="BTC-USD",
    side="buy",
    method="market",
    intended_price=50_000.0,
    actual_price=50_010.0,
    intended_size=0.1,
    filled_size=0.1,
    latency_ms=100.0,
) -> ExecutionSample:
    return ExecutionSample(
        venue=venue,
        symbol=symbol,
        side=side,
        execution_method=method,
        intended_price=intended_price,
        actual_price=actual_price,
        intended_size=intended_size,
        filled_size=filled_size,
        latency_ms=latency_ms,
    )


class TestExecutionSample:
    def test_slippage_bps_buy(self):
        s = _make_sample(intended_price=50_000, actual_price=50_100)
        # 100/50000 * 10000 = 20 bps
        assert s.slippage_bps == pytest.approx(20.0, rel=0.01)

    def test_slippage_bps_sell_adverse(self):
        s = _make_sample(side="sell", intended_price=50_000, actual_price=49_900)
        # For sell: adverse = actual < intended → slippage = -(49900-50000)/50000*10000
        assert s.slippage_bps == pytest.approx(20.0, rel=0.01)

    def test_fill_rate_full(self):
        s = _make_sample(intended_size=1.0, filled_size=1.0)
        assert s.fill_rate == pytest.approx(1.0)

    def test_fill_rate_partial(self):
        s = _make_sample(intended_size=1.0, filled_size=0.7)
        assert s.fill_rate == pytest.approx(0.7)

    def test_fill_rate_capped_at_one(self):
        s = _make_sample(intended_size=1.0, filled_size=1.5)
        assert s.fill_rate == pytest.approx(1.0)

    def test_slippage_zero_intended_price(self):
        s = _make_sample(intended_price=0.0, actual_price=100.0)
        assert s.slippage_bps == 0.0


class TestMultiVenueCalibrator:
    @pytest.fixture
    def calibrator(self):
        return MultiVenueCalibrator(venues=["coinbase", "kraken"])

    def test_record_single_sample(self, calibrator):
        calibrator.record_execution(_make_sample(venue="coinbase"))
        assert calibrator.sample_count("coinbase") == 1

    def test_unknown_venue_ignored(self, calibrator):
        calibrator.record_execution(_make_sample(venue="unknown_exchange"))
        assert calibrator.sample_count("unknown_exchange") == 0

    def test_batch_record(self, calibrator):
        samples = [_make_sample(venue="kraken") for _ in range(5)]
        calibrator.record_executions(samples)
        assert calibrator.sample_count("kraken") == 5

    def test_get_venue_stats_empty(self, calibrator):
        stats = calibrator.get_venue_stats("coinbase")
        assert isinstance(stats, VenueStats)
        assert stats.sample_count == 0

    def test_get_venue_stats_with_data(self, calibrator):
        for _ in range(10):
            calibrator.record_execution(_make_sample(venue="coinbase", latency_ms=120))
        stats = calibrator.get_venue_stats("coinbase")
        assert stats.sample_count == 10
        assert stats.avg_latency_ms == pytest.approx(120.0)

    def test_get_all_stats(self, calibrator):
        calibrator.record_execution(_make_sample(venue="coinbase"))
        all_stats = calibrator.get_all_stats()
        assert "coinbase" in all_stats
        assert "kraken" in all_stats

    def test_compute_recommendations_no_data(self, calibrator):
        rec = calibrator.compute_recommendations()
        assert isinstance(rec, RoutingRecommendation)
        assert "no data" in " ".join(rec.notes).lower()

    def test_compute_recommendations_with_data(self, calibrator):
        # Coinbase has better data (lower slippage)
        for _ in range(20):
            calibrator.record_execution(
                _make_sample(venue="coinbase", intended_price=50_000, actual_price=50_005, latency_ms=100)
            )
        for _ in range(20):
            calibrator.record_execution(
                _make_sample(venue="kraken", intended_price=50_000, actual_price=50_050, latency_ms=300)
            )
        rec = calibrator.compute_recommendations()
        assert rec.recommended_primary_venue == "coinbase"

    def test_list_venues(self, calibrator):
        assert set(calibrator.list_venues()) == {"coinbase", "kraken"}

    def test_get_none_for_unknown_venue(self, calibrator):
        assert calibrator.get_venue_stats("nonexistent") is None

    def test_singleton(self):
        a = get_multi_venue_calibrator()
        b = get_multi_venue_calibrator()
        assert a is b
