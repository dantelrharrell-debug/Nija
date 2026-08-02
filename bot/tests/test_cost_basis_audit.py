"""Tests for bot.cost_basis_audit."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bot.cost_basis_audit import (
    AuditDiscrepancy,
    AuditRunResult,
    CostBasisAudit,
    run_cost_basis_audit,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker(positions):
    tracker = MagicMock()
    tracker.positions = dict(positions)
    tracker._save_positions = MagicMock()
    return tracker


def _make_broker_with_balance(balances=None):
    broker = MagicMock()
    broker.api = MagicMock()
    # Simulate Kraken Balance call via _kraken_api_call
    broker._kraken_api_call.return_value = {"result": balances or {}}
    return broker


# ---------------------------------------------------------------------------
# CostBasisAudit.run_once — clean positions
# ---------------------------------------------------------------------------

class TestRunOnceClean:
    def test_no_discrepancies_when_all_verified(self):
        tracker = _make_tracker({
            "BTC-USD": {
                "quantity": 1.0,
                "entry_price": 50_000.0,
                "cost_basis_verified": True,
                "size_usd": 50_000.0,
            }
        })
        broker = _make_broker_with_balance({"XXBT": "1.0"})
        audit = CostBasisAudit(tracker, broker, broker_name="kraken", auto_repair=False)
        result = audit.run_once()
        assert isinstance(result, AuditRunResult)
        assert result.positions_checked == 1
        assert result.unverified_positions == 0

    def test_result_includes_timestamp_and_broker(self):
        tracker = _make_tracker({})
        broker = _make_broker_with_balance()
        audit = CostBasisAudit(tracker, broker, broker_name="kraken")
        result = audit.run_once()
        assert result.broker_name == "kraken"
        assert result.timestamp != ""


# ---------------------------------------------------------------------------
# Unverified position detection
# ---------------------------------------------------------------------------

class TestUnverifiedDetection:
    def test_flags_unverified_position(self):
        tracker = _make_tracker({
            "ORCA-USD": {
                "quantity": 100.0,
                "entry_price": 0.0,
                "cost_basis_verified": False,
                "size_usd": 500.0,
            }
        })
        broker = _make_broker_with_balance()
        audit = CostBasisAudit(tracker, broker, broker_name="kraken", auto_repair=False)
        result = audit.run_once()
        assert result.unverified_positions == 1
        assert any(d.discrepancy_type == "unverified" for d in result.discrepancies)

    def test_auto_repair_triggers_reconciler(self):
        tracker = _make_tracker({
            "ETH-USD": {
                "quantity": 1.0,
                "entry_price": 0.0,
                "cost_basis_verified": False,
                "size_usd": 3000.0,
            }
        })
        broker = _make_broker_with_balance()
        audit = CostBasisAudit(tracker, broker, broker_name="kraken", auto_repair=True)
        # Patch the reconciler so it reports "verified"
        with patch("bot.cost_basis_audit.CostBasisReconciler") as MockReconciler:
            mock_instance = MagicMock()
            MockReconciler.return_value = mock_instance
            mock_instance.reconcile_symbol.return_value = MagicMock(status="verified")
            result = audit.run_once()
        assert result.discrepancies_repaired == 1


# ---------------------------------------------------------------------------
# Quantity mismatch detection and repair
# ---------------------------------------------------------------------------

class TestQtyMismatch:
    def test_flags_qty_mismatch(self):
        tracker = _make_tracker({
            "BTC-USD": {
                "quantity": 2.0,
                "entry_price": 50_000.0,
                "cost_basis_verified": True,
                "size_usd": 100_000.0,
            }
        })
        # Broker says 1.0 BTC
        broker = MagicMock()
        broker._kraken_api_call.return_value = {"result": {"XXBT": "1.0"}}
        audit = CostBasisAudit(tracker, broker, broker_name="kraken", auto_repair=False)
        result = audit.run_once()
        qty_mismatches = [d for d in result.discrepancies if d.discrepancy_type == "qty_mismatch"]
        assert len(qty_mismatches) == 1
        assert qty_mismatches[0].stored_value == pytest.approx(2.0)
        assert qty_mismatches[0].broker_value == pytest.approx(1.0)

    def test_auto_repairs_qty_mismatch(self):
        tracker = _make_tracker({
            "BTC-USD": {
                "quantity": 2.0,
                "entry_price": 50_000.0,
                "cost_basis_verified": True,
                "size_usd": 100_000.0,
            }
        })
        broker = MagicMock()
        broker._kraken_api_call.return_value = {"result": {"XXBT": "1.0"}}
        audit = CostBasisAudit(tracker, broker, broker_name="kraken", auto_repair=True)
        result = audit.run_once()
        repaired = [d for d in result.discrepancies if d.discrepancy_type == "qty_mismatch" and d.repaired]
        assert len(repaired) == 1
        assert tracker.positions["BTC-USD"]["quantity"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Fill price mismatch
# ---------------------------------------------------------------------------

class TestFillPriceMismatch:
    def test_flags_price_mismatch(self):
        tracker = _make_tracker({
            "BTC-USD": {
                "quantity": 1.0,
                "entry_price": 50_000.0,
                "cost_basis_verified": True,
                "size_usd": 50_000.0,
            }
        })
        broker = _make_broker_with_balance({"XXBT": "1.0"})
        audit = CostBasisAudit(
            tracker, broker, broker_name="kraken",
            auto_repair=False, price_tolerance=0.02,
        )
        # Patch _compute_vwap to return a discrepant price
        with patch("bot.cost_basis_audit._compute_vwap", return_value=55_000.0):
            result = audit.run_once()
        price_mismatches = [d for d in result.discrepancies if d.discrepancy_type == "fill_price_mismatch"]
        assert len(price_mismatches) == 1
        assert price_mismatches[0].broker_value == pytest.approx(55_000.0)

    def test_no_mismatch_within_tolerance(self):
        tracker = _make_tracker({
            "BTC-USD": {
                "quantity": 1.0,
                "entry_price": 50_000.0,
                "cost_basis_verified": True,
                "size_usd": 50_000.0,
            }
        })
        broker = _make_broker_with_balance()
        audit = CostBasisAudit(
            tracker, broker, broker_name="kraken",
            auto_repair=False, price_tolerance=0.10,  # 10% tolerance
        )
        # 1% difference — within 10% tolerance → no flag
        with patch("bot.cost_basis_audit._compute_vwap", return_value=50_500.0):
            result = audit.run_once()
        price_mismatches = [d for d in result.discrepancies if d.discrepancy_type == "fill_price_mismatch"]
        assert len(price_mismatches) == 0


# ---------------------------------------------------------------------------
# get_results / get_latest_result
# ---------------------------------------------------------------------------

class TestResultHistory:
    def test_get_latest_result_after_run(self):
        tracker = _make_tracker({})
        broker = _make_broker_with_balance()
        audit = CostBasisAudit(tracker, broker, broker_name="kraken")
        assert audit.get_latest_result() is None
        audit.run_once()
        latest = audit.get_latest_result()
        assert isinstance(latest, AuditRunResult)

    def test_multiple_runs_accumulate_results(self):
        tracker = _make_tracker({})
        broker = _make_broker_with_balance()
        audit = CostBasisAudit(tracker, broker, broker_name="kraken")
        audit.run_once()
        audit.run_once()
        assert len(audit.get_results()) == 2


# ---------------------------------------------------------------------------
# run_cost_basis_audit (convenience function)
# ---------------------------------------------------------------------------

class TestRunCostBasisAudit:
    def test_returns_audit_run_result(self):
        tracker = _make_tracker({})
        broker = _make_broker_with_balance()
        result = run_cost_basis_audit(tracker, broker, broker_name="kraken")
        assert isinstance(result, AuditRunResult)
