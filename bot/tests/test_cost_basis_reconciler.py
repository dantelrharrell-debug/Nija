"""Tests for bot.cost_basis_reconciler."""
from __future__ import annotations

import threading
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from bot.cost_basis_reconciler import (
    CostBasisReconciler,
    FillRecord,
    ReconciliationResult,
    _KrakenFillAdapter,
    _OKXFillAdapter,
    _reconstruct_vwap,
    is_auto_manageable,
    reconcile_broker_positions,
)


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------

def _make_tracker(positions: Dict[str, Dict]) -> Any:
    """Create a minimal fake position tracker."""
    tracker = MagicMock()
    tracker.positions = positions
    tracker._save_positions = MagicMock()
    return tracker


def _fills(*args) -> List[FillRecord]:
    """Shorthand to build FillRecord lists inline.
    Each arg is (side, qty, price, fee=0, ts=0).
    """
    result = []
    for i, a in enumerate(args):
        side, qty, price = a[0], a[1], a[2]
        fee = a[3] if len(a) > 3 else 0.0
        result.append(FillRecord(timestamp=float(i), side=side, quantity=qty, price=price, fee=fee))
    return result


# ---------------------------------------------------------------------------
# _reconstruct_vwap
# ---------------------------------------------------------------------------

class TestReconstructVwap:
    def test_single_buy(self):
        fills = _fills(("buy", 1.0, 50_000.0))
        qty, vwap = _reconstruct_vwap(fills)
        assert abs(qty - 1.0) < 1e-9
        assert abs(vwap - 50_000.0) < 1e-6

    def test_two_buys(self):
        fills = _fills(("buy", 1.0, 40_000.0), ("buy", 1.0, 60_000.0))
        qty, vwap = _reconstruct_vwap(fills)
        assert abs(qty - 2.0) < 1e-9
        assert abs(vwap - 50_000.0) < 1e-6

    def test_buy_then_partial_sell(self):
        fills = _fills(("buy", 2.0, 50_000.0), ("sell", 1.0, 55_000.0))
        qty, vwap = _reconstruct_vwap(fills)
        # Remaining 1 unit at original cost
        assert abs(qty - 1.0) < 1e-9
        assert abs(vwap - 50_000.0) < 1e-6

    def test_sell_all_returns_zero(self):
        fills = _fills(("buy", 1.0, 50_000.0), ("sell", 1.0, 55_000.0))
        qty, vwap = _reconstruct_vwap(fills)
        assert qty < 1e-9
        assert vwap == 0.0

    def test_fee_included_in_cost(self):
        fills = _fills(("buy", 1.0, 50_000.0, 50.0))
        qty, vwap = _reconstruct_vwap(fills)
        assert abs(qty - 1.0) < 1e-9
        assert abs(vwap - 50_050.0) < 1e-6   # fee folded in

    def test_empty_fills_returns_zeros(self):
        qty, vwap = _reconstruct_vwap([])
        assert qty == 0.0
        assert vwap == 0.0


# ---------------------------------------------------------------------------
# _KrakenFillAdapter
# ---------------------------------------------------------------------------

class TestKrakenFillAdapter:
    def _make_broker(self, trades: Dict) -> Any:
        broker = MagicMock()
        broker.api = MagicMock()
        broker.api.query_private.return_value = {
            "result": {"trades": trades, "count": len(trades)}
        }
        return broker

    def test_filters_by_symbol(self):
        broker = self._make_broker({
            "t1": {"pair": "XXBTZUSD", "type": "buy", "vol": "1.0", "price": "50000", "fee": "0", "time": "1000"},
            "t2": {"pair": "XETHZUSD", "type": "buy", "vol": "2.0", "price": "3000", "fee": "0", "time": "1001"},
        })
        adapter = _KrakenFillAdapter(broker)
        fills = adapter.get_fills("BTC-USD")
        assert len(fills) == 1
        assert abs(fills[0].price - 50_000) < 1e-6

    def test_returns_empty_on_api_error(self):
        broker = MagicMock()
        broker.api = MagicMock()
        broker.api.query_private.return_value = {"error": ["EGeneral:Invalid arguments"]}
        adapter = _KrakenFillAdapter(broker)
        fills = adapter.get_fills("BTC-USD")
        assert fills == []

    def test_sorted_by_timestamp(self):
        broker = self._make_broker({
            "t1": {"pair": "XXBTZUSD", "type": "buy", "vol": "1", "price": "50000", "fee": "0", "time": "2000"},
            "t2": {"pair": "XXBTZUSD", "type": "buy", "vol": "1", "price": "51000", "fee": "0", "time": "1000"},
        })
        adapter = _KrakenFillAdapter(broker)
        fills = adapter.get_fills("BTC-USD")
        assert fills[0].timestamp < fills[1].timestamp


# ---------------------------------------------------------------------------
# _OKXFillAdapter
# ---------------------------------------------------------------------------

class TestOKXFillAdapter:
    def _make_broker(self, data: list) -> Any:
        broker = MagicMock()
        broker.trade_api = MagicMock()
        broker.trade_api.get_fills.return_value = {"code": "0", "data": data}
        return broker

    def test_basic_buy_fills(self):
        broker = self._make_broker([
            {"side": "buy", "fillSz": "0.5", "fillPx": "60000", "fee": "0", "ts": "1000000"},
        ])
        adapter = _OKXFillAdapter(broker)
        fills = adapter.get_fills("BTC-USD")
        assert len(fills) == 1
        assert abs(fills[0].price - 60_000) < 1e-6

    def test_api_failure_returns_empty(self):
        broker = MagicMock()
        broker.trade_api = MagicMock()
        broker.trade_api.get_fills.return_value = {"code": "51001", "data": []}
        adapter = _OKXFillAdapter(broker)
        fills = adapter.get_fills("BTC-USD")
        assert fills == []


# ---------------------------------------------------------------------------
# CostBasisReconciler
# ---------------------------------------------------------------------------

class TestCostBasisReconciler:
    def _make_kraken_broker(self, trades: Dict) -> Any:
        broker = MagicMock()
        broker.api = MagicMock()
        broker.api.query_private.return_value = {
            "result": {"trades": trades, "count": len(trades)}
        }
        return broker

    def test_skips_already_verified_positions(self):
        tracker = _make_tracker({
            "BTC-USD": {"quantity": 1.0, "entry_price": 50000.0, "cost_basis_verified": True},
        })
        broker = self._make_kraken_broker({})
        reconciler = CostBasisReconciler(tracker, broker, broker_name="kraken")
        results = reconciler.run_sync()
        assert results == []
        tracker._save_positions.assert_not_called()

    def test_verifies_position_when_history_matches(self):
        tracker = _make_tracker({
            "BTC-USD": {
                "quantity": 1.0,
                "entry_price": 0.0,
                "cost_basis_verified": False,
                "size_usd": 50000.0,
            }
        })
        broker = self._make_kraken_broker({
            "t1": {"pair": "XXBTZUSD", "type": "buy", "vol": "1.0",
                   "price": "50000", "fee": "0", "time": "1000"},
        })
        reconciler = CostBasisReconciler(tracker, broker, broker_name="kraken")
        results = reconciler.run_sync()
        assert len(results) == 1
        assert results[0].status == "verified"
        assert abs(results[0].entry_price - 50_000) < 1e-6
        assert results[0].auto_exit_blocked is False
        # Tracker should be updated
        tracker._save_positions.assert_called()
        assert tracker.positions["BTC-USD"]["cost_basis_verified"] is True

    def test_adopts_position_when_no_history(self):
        tracker = _make_tracker({
            "ORCA-USD": {
                "quantity": 100.0,
                "entry_price": 0.0,
                "cost_basis_verified": False,
                "last_broker_snapshot_price": 5.0,
                "size_usd": 500.0,
            }
        })
        broker = self._make_kraken_broker({})  # no trades returned
        reconciler = CostBasisReconciler(tracker, broker, broker_name="kraken")
        results = reconciler.run_sync()
        assert len(results) == 1
        assert results[0].status == "adopted"
        assert results[0].fills_used == 0

    def test_skips_dust_position(self):
        tracker = _make_tracker({
            "BTC-USD": {
                "quantity": 0.00000001,
                "entry_price": 0.0,
                "cost_basis_verified": False,
                "last_broker_snapshot_price": 50000.0,
                "size_usd": 0.0005,
            }
        })
        broker = self._make_kraken_broker({})
        reconciler = CostBasisReconciler(tracker, broker, broker_name="kraken", dust_threshold_usd=1.0)
        results = reconciler.run_sync()
        assert len(results) == 1
        assert results[0].status == "skipped"
        assert "dust" in results[0].details

    def test_adoption_policy_block_sets_auto_exit_blocked(self, monkeypatch):
        monkeypatch.setenv("NIJA_ADOPTED_POSITION_POLICY", "block")
        tracker = _make_tracker({
            "ETH-USD": {"quantity": 1.0, "cost_basis_verified": False, "size_usd": 2000.0}
        })
        broker = self._make_kraken_broker({})
        reconciler = CostBasisReconciler(tracker, broker, broker_name="kraken")
        results = reconciler.run_sync()
        assert results[0].auto_exit_blocked is True

    def test_adoption_policy_allow_clears_auto_exit_blocked(self, monkeypatch):
        monkeypatch.setenv("NIJA_ADOPTED_POSITION_POLICY", "allow")
        tracker = _make_tracker({
            "ETH-USD": {"quantity": 1.0, "cost_basis_verified": False, "size_usd": 2000.0}
        })
        broker = self._make_kraken_broker({})
        reconciler = CostBasisReconciler(tracker, broker, broker_name="kraken")
        results = reconciler.run_sync()
        assert results[0].auto_exit_blocked is False

    def test_unknown_broker_returns_empty(self):
        tracker = _make_tracker({"X-USD": {"quantity": 1.0, "cost_basis_verified": False}})
        broker = MagicMock()
        reconciler = CostBasisReconciler(tracker, broker, broker_name="unknown_exchange")
        results = reconciler.run_sync()
        assert results == []


# ---------------------------------------------------------------------------
# is_auto_manageable
# ---------------------------------------------------------------------------

class TestIsAutoManageable:
    def test_verified_is_manageable(self):
        assert is_auto_manageable({"cost_basis_verified": True}) is True

    def test_unverified_no_policy_is_not_manageable(self):
        assert is_auto_manageable({"cost_basis_verified": False}) is False

    def test_adopted_allow_policy_is_manageable(self):
        pos = {
            "cost_basis_verified": False,
            "position_adoption_policy": "allow",
            "auto_manage_adopted": True,
        }
        assert is_auto_manageable(pos) is True

    def test_adopted_block_policy_is_not_manageable(self):
        pos = {
            "cost_basis_verified": False,
            "position_adoption_policy": "block",
            "auto_manage_adopted": False,
        }
        assert is_auto_manageable(pos) is False
