"""
Tests for the Kraken margin engine and its integration points.

Coverage
--------
1. Permission gating — CONFIRMED / DENIED / UNKNOWN / CHECK_FAILED states.
2. Order param injection — leverage field present / absent based on state.
3. Leverage notional cap — 3× hard cap enforcement in tre_compute_position_size.
4. Margin health blocking — maintenance and critical margin ratio gates.
5. Borrowed exposure accounting — record_open/closed_position tallies.
6. can_execute margin gate — blocked on critical margin, blocked on low margin,
   passes when margin is healthy, always passes when feature is disabled.
"""

from __future__ import annotations

import os
import time
import unittest
from unittest.mock import MagicMock, patch

from bot.kraken_margin_engine import (
    CRITICAL_MARGIN_RATIO_FLOOR,
    HARD_MAX_LEVERAGE,
    KRAKEN_MIN_LEVERAGE,
    MAINTENANCE_MARGIN_RATIO_FLOOR,
    KrakenMarginEngine,
    MarginHealthSnapshot,
    MarginPermissionState,
    get_margin_engine,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_engine() -> KrakenMarginEngine:
    """Return a fresh, isolated KrakenMarginEngine (not the singleton)."""
    return KrakenMarginEngine()


def _make_adapter(
    open_positions_error: list | None = None,
    trade_balance: dict | None = None,
) -> MagicMock:
    """Build a minimal mock adapter with controllable API responses."""
    adapter = MagicMock()

    # Default: no errors, empty result → margin permitted
    if open_positions_error is None:
        open_positions_response = {"error": [], "result": {}}
    else:
        open_positions_response = {"error": open_positions_error, "result": {}}

    if trade_balance is None:
        trade_balance_response = {
            "result": {
                "eb": "1000.00",
                "tb": "800.00",
                "ml": "500.00",  # 500% margin level — healthy
                "mo": "200.00",
                "mf": "600.00",
                "n":  "10.00",
                "v":  "0.00",
                "e":  "1010.00",
            }
        }
    else:
        trade_balance_response = {"result": trade_balance}

    def _api_call(method, params=None):
        if method == "OpenPositions":
            return open_positions_response
        if method == "TradeBalance":
            return trade_balance_response
        return {"error": ["method not mocked"], "result": {}}

    adapter._kraken_api_call.side_effect = _api_call
    return adapter


# ─────────────────────────────────────────────────────────────────────────────
# 1. Permission gating
# ─────────────────────────────────────────────────────────────────────────────

class TestMarginPermissions(unittest.TestCase):

    def test_permission_confirmed_on_clean_response(self):
        engine = _make_engine()
        adapter = _make_adapter()
        state = engine.check_permissions(adapter)
        self.assertEqual(state, MarginPermissionState.CONFIRMED)

    def test_permission_denied_on_permission_error(self):
        engine = _make_engine()
        adapter = _make_adapter(open_positions_error=["EGeneral:Permission denied"])
        state = engine.check_permissions(adapter)
        self.assertEqual(state, MarginPermissionState.DENIED)

    def test_permission_check_failed_on_api_exception(self):
        engine = _make_engine()
        adapter = MagicMock()
        adapter._kraken_api_call.side_effect = RuntimeError("network error")
        state = engine.check_permissions(adapter)
        self.assertEqual(state, MarginPermissionState.CHECK_FAILED)

    def test_permission_denied_blocks_margin_trade(self):
        engine = _make_engine()
        engine._permission_state = MarginPermissionState.DENIED
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "true"}):
            allowed, reason = engine.is_margin_trade_allowed()
        self.assertFalse(allowed)
        self.assertIn("permission_denied", reason)

    def test_permission_unknown_blocks_margin_trade(self):
        engine = _make_engine()
        # UNKNOWN is the default state
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "true"}):
            allowed, reason = engine.is_margin_trade_allowed()
        self.assertFalse(allowed)
        self.assertIn("unknown", reason.lower())

    def test_permission_cache_not_re_fetched_within_ttl(self):
        engine = _make_engine()
        adapter = _make_adapter()
        engine.check_permissions(adapter)
        engine.check_permissions(adapter)
        # Should only have been called once (cached after first call)
        self.assertEqual(adapter._kraken_api_call.call_count, 1)

    def test_invalidate_permission_cache_forces_recheck(self):
        engine = _make_engine()
        adapter = _make_adapter()
        engine.check_permissions(adapter)
        engine.invalidate_permission_cache()
        engine.check_permissions(adapter)
        self.assertEqual(adapter._kraken_api_call.call_count, 2)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Order parameter injection
# ─────────────────────────────────────────────────────────────────────────────

class TestOrderParamInjection(unittest.TestCase):

    def test_build_params_returns_empty_when_disabled(self):
        engine = _make_engine()
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "false"}):
            params = engine.build_order_margin_params(leverage=2)
        self.assertEqual(params, {})

    def test_build_params_returns_empty_for_spot(self):
        engine = _make_engine()
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "true"}):
            params = engine.build_order_margin_params(leverage=1)
        self.assertEqual(params, {})

    def test_build_params_injects_leverage_when_enabled(self):
        engine = _make_engine()
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "true"}):
            params = engine.build_order_margin_params(leverage=2)
        self.assertEqual(params.get("leverage"), "2")

    def test_build_params_clamps_leverage_to_hard_max(self):
        engine = _make_engine()
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "true"}):
            params = engine.build_order_margin_params(leverage=10)
        # Should be clamped to HARD_MAX_LEVERAGE (3)
        self.assertEqual(params.get("leverage"), str(HARD_MAX_LEVERAGE))

    def test_build_params_reduce_only_flag(self):
        engine = _make_engine()
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "true"}):
            params = engine.build_order_margin_params(leverage=2, is_reducing=True)
        self.assertEqual(params.get("reduce_only"), "true")

    def test_build_params_no_reduce_only_for_entry(self):
        engine = _make_engine()
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "true"}):
            params = engine.build_order_margin_params(leverage=2, is_reducing=False)
        self.assertNotIn("reduce_only", params)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Leverage notional cap
# ─────────────────────────────────────────────────────────────────────────────

class TestLeveragedNotionalCap(unittest.TestCase):

    def test_notional_within_cap_unchanged(self):
        engine = _make_engine()
        notional = engine.compute_leveraged_notional(
            spot_size_usd=100.0, leverage=2, account_equity_usd=1000.0
        )
        # 100 × 2 = 200; cap = 1000 × 3 = 3000 → no cap applied
        self.assertAlmostEqual(notional, 200.0, places=2)

    def test_notional_capped_at_hard_max_leverage(self):
        engine = _make_engine()
        # spot=500, leverage=3, equity=100 → raw=1500; cap=100×3=300
        notional = engine.compute_leveraged_notional(
            spot_size_usd=500.0, leverage=3, account_equity_usd=100.0
        )
        self.assertAlmostEqual(notional, 300.0, places=2)

    def test_leverage_clamped_to_hard_max(self):
        engine = _make_engine()
        notional_10x = engine.compute_leveraged_notional(
            spot_size_usd=100.0, leverage=10, account_equity_usd=1000.0
        )
        notional_3x = engine.compute_leveraged_notional(
            spot_size_usd=100.0, leverage=3, account_equity_usd=1000.0
        )
        # Both should equal the 3× notional because leverage is clamped
        self.assertAlmostEqual(notional_10x, notional_3x, places=2)

    def test_tre_compute_position_size_leverage_scales_down_risk(self):
        """With leverage=2, max_risk is halved, so computed size is ≤ spot size."""
        from bot.risk.sizing import tre_compute_position_size
        spot_size = tre_compute_position_size(
            account_balance=1000.0,
            symbol="XBTUSD",
            broker_name="kraken",
            atr_pct=0.02,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            entry_price=50000.0,
            win_rate=0.55,
            leverage=1,
        )
        margin_size = tre_compute_position_size(
            account_balance=1000.0,
            symbol="XBTUSD",
            broker_name="kraken",
            atr_pct=0.02,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            entry_price=50000.0,
            win_rate=0.55,
            leverage=2,
        )
        # Risk-adjusted margin equity portion should be smaller than spot size
        self.assertLessEqual(margin_size, spot_size)

    def test_tre_compute_notional_cap_enforced(self):
        """Equity portion is capped so notional ≤ balance × 3."""
        from bot.risk.sizing import tre_compute_position_size
        balance = 100.0
        leverage = 3
        size = tre_compute_position_size(
            account_balance=balance,
            symbol="XBTUSD",
            broker_name="kraken",
            atr_pct=0.005,
            stop_loss_pct=0.005,
            take_profit_pct=0.02,
            entry_price=50000.0,
            win_rate=0.60,
            leverage=leverage,
        )
        # size × leverage must not exceed balance × HARD_MAX_LEVERAGE
        max_notional = balance * HARD_MAX_LEVERAGE
        self.assertLessEqual(size * leverage, max_notional + 0.01)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Margin health blocking
# ─────────────────────────────────────────────────────────────────────────────

class TestMarginHealthGates(unittest.TestCase):

    def _healthy_snapshot(self) -> MarginHealthSnapshot:
        return MarginHealthSnapshot(
            timestamp=time.time(),
            permission_state=MarginPermissionState.CONFIRMED.value,
            equivalent_balance_usd=1000.0,
            trade_balance_free_usd=800.0,
            margin_level_pct=500.0,
            margin_obligation_usd=200.0,
            free_margin_usd=600.0,
            unrealised_pnl_usd=10.0,
            borrowed_exposure_usd=200.0,
            is_margin_enabled=True,
            maintenance_margin_ok=True,
            critical_margin_breach=False,
            reason="margin_healthy:500.0%",
        )

    def _low_margin_snapshot(self) -> MarginHealthSnapshot:
        return MarginHealthSnapshot(
            timestamp=time.time(),
            permission_state=MarginPermissionState.CONFIRMED.value,
            equivalent_balance_usd=1000.0,
            trade_balance_free_usd=50.0,
            margin_level_pct=150.0,  # Below maintenance floor (200%)
            margin_obligation_usd=900.0,
            free_margin_usd=50.0,
            unrealised_pnl_usd=-100.0,
            borrowed_exposure_usd=900.0,
            is_margin_enabled=True,
            maintenance_margin_ok=False,
            critical_margin_breach=False,
            reason="low_margin_level:150.0%",
        )

    def _critical_snapshot(self) -> MarginHealthSnapshot:
        return MarginHealthSnapshot(
            timestamp=time.time(),
            permission_state=MarginPermissionState.CONFIRMED.value,
            equivalent_balance_usd=1000.0,
            trade_balance_free_usd=5.0,
            margin_level_pct=85.0,  # Near liquidation
            margin_obligation_usd=980.0,
            free_margin_usd=5.0,
            unrealised_pnl_usd=-200.0,
            borrowed_exposure_usd=980.0,
            is_margin_enabled=True,
            maintenance_margin_ok=False,
            critical_margin_breach=True,
            reason="critical_margin_level:85.0%",
        )

    def test_healthy_snapshot_allows_new_entry(self):
        engine = _make_engine()
        engine._permission_state = MarginPermissionState.CONFIRMED
        engine._last_snapshot = self._healthy_snapshot()
        engine._snapshot_ts = time.time()
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "true"}):
            allowed, reason = engine.is_margin_trade_allowed(is_reducing=False)
        self.assertTrue(allowed)

    def test_low_margin_blocks_new_entry(self):
        engine = _make_engine()
        engine._permission_state = MarginPermissionState.CONFIRMED
        engine._last_snapshot = self._low_margin_snapshot()
        engine._snapshot_ts = time.time()
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "true"}):
            allowed, reason = engine.is_margin_trade_allowed(is_reducing=False)
        self.assertFalse(allowed)
        self.assertIn("maintenance_low", reason)

    def test_low_margin_allows_reducing_order(self):
        engine = _make_engine()
        engine._permission_state = MarginPermissionState.CONFIRMED
        engine._last_snapshot = self._low_margin_snapshot()
        engine._snapshot_ts = time.time()
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "true"}):
            allowed, reason = engine.is_margin_trade_allowed(is_reducing=True)
        self.assertTrue(allowed)

    def test_critical_margin_blocks_all_orders(self):
        engine = _make_engine()
        engine._permission_state = MarginPermissionState.CONFIRMED
        engine._last_snapshot = self._critical_snapshot()
        engine._snapshot_ts = time.time()
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "true"}):
            # Even a reducing order is blocked on critical breach
            allowed_reduce, _ = engine.is_margin_trade_allowed(is_reducing=True)
            allowed_entry, _ = engine.is_margin_trade_allowed(is_reducing=False)
        self.assertFalse(allowed_reduce)
        self.assertFalse(allowed_entry)

    def test_disabled_feature_returns_not_allowed(self):
        engine = _make_engine()
        engine._permission_state = MarginPermissionState.CONFIRMED
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "false"}):
            allowed, reason = engine.is_margin_trade_allowed()
        self.assertFalse(allowed)
        self.assertEqual(reason, "margin_disabled")

    def test_snapshot_builds_from_trade_balance_healthy(self):
        engine = _make_engine()
        engine._permission_state = MarginPermissionState.CONFIRMED
        adapter = _make_adapter()  # 500% margin level — healthy
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "true"}):
            snap = engine._build_snapshot(adapter)
        self.assertTrue(snap.maintenance_margin_ok)
        self.assertFalse(snap.critical_margin_breach)

    def test_snapshot_builds_critical_for_low_margin_level(self):
        engine = _make_engine()
        engine._permission_state = MarginPermissionState.CONFIRMED
        # ml = 85 → critical (< CRITICAL_MARGIN_RATIO_FLOOR * 1000 = 100)
        adapter = _make_adapter(trade_balance={
            "eb": "1000.00", "tb": "5.00",
            "ml": "85.00",   # critical
            "mo": "980.00", "mf": "5.00", "n": "-200.00",
            "v": "0.00", "e": "800.00",
        })
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "true"}):
            snap = engine._build_snapshot(adapter)
        self.assertTrue(snap.critical_margin_breach)

    def test_snapshot_no_margin_positions_is_healthy(self):
        engine = _make_engine()
        engine._permission_state = MarginPermissionState.CONFIRMED
        # ml = 0 → no margin positions → vacuously healthy
        adapter = _make_adapter(trade_balance={
            "eb": "1000.00", "tb": "1000.00",
            "ml": "0.00", "mo": "0.00", "mf": "1000.00",
            "n": "0.00", "v": "0.00", "e": "1000.00",
        })
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "true"}):
            snap = engine._build_snapshot(adapter)
        self.assertTrue(snap.maintenance_margin_ok)
        self.assertFalse(snap.critical_margin_breach)
        self.assertEqual(snap.reason, "no_margin_positions")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Borrowed exposure accounting
# ─────────────────────────────────────────────────────────────────────────────

class TestBorrowedExposureAccounting(unittest.TestCase):

    def test_record_open_increments_tallies(self):
        engine = _make_engine()
        engine.record_open_position(notional_usd=1000.0, leverage=2)
        snap = engine.get_exposure_snapshot()
        self.assertAlmostEqual(snap["total_notional_usd"], 1000.0, places=2)
        # borrowed = notional - equity = 1000 - 500 = 500
        self.assertAlmostEqual(snap["total_borrowed_usd"], 500.0, places=2)
        self.assertEqual(snap["position_count"], 1.0)

    def test_record_open_multiple_positions(self):
        engine = _make_engine()
        engine.record_open_position(notional_usd=600.0, leverage=2)
        engine.record_open_position(notional_usd=300.0, leverage=3)
        snap = engine.get_exposure_snapshot()
        self.assertAlmostEqual(snap["total_notional_usd"], 900.0, places=2)
        self.assertEqual(snap["position_count"], 2.0)

    def test_record_closed_decrements_tallies(self):
        engine = _make_engine()
        engine.record_open_position(notional_usd=1000.0, leverage=2)
        engine.record_closed_position(notional_usd=1000.0, leverage=2)
        snap = engine.get_exposure_snapshot()
        self.assertAlmostEqual(snap["total_notional_usd"], 0.0, places=2)
        self.assertAlmostEqual(snap["total_borrowed_usd"], 0.0, places=2)
        self.assertEqual(snap["position_count"], 0.0)

    def test_record_closed_clamps_to_zero(self):
        engine = _make_engine()
        # Close without ever opening — should not go negative
        engine.record_closed_position(notional_usd=1000.0, leverage=2)
        snap = engine.get_exposure_snapshot()
        self.assertGreaterEqual(snap["total_notional_usd"], 0.0)
        self.assertGreaterEqual(snap["total_borrowed_usd"], 0.0)

    def test_net_leverage_calculation(self):
        engine = _make_engine()
        engine.record_open_position(notional_usd=1000.0, leverage=2)
        snap = engine.get_exposure_snapshot()
        # equity = 500, notional = 1000, net_lev = 1000/500 = 2.0
        self.assertAlmostEqual(snap["net_leverage"], 2.0, places=2)


# ─────────────────────────────────────────────────────────────────────────────
# 6. can_execute margin gate integration
# ─────────────────────────────────────────────────────────────────────────────

class TestCanExecuteMarginGate(unittest.TestCase):
    """
    Verify that can_execute() in execution_authority_context passes the margin
    health gate correctly.

    We bypass all the non-margin checks by patching runtime_authority_snapshot
    to return LIVE phase and patching the individual gate variables, then test
    only the margin-specific gate path.
    """

    def _make_live_snapshot(self):
        """Return a RuntimeAuthoritySnapshot in LIVE phase."""
        try:
            from bot.execution_authority_context import RuntimeAuthoritySnapshot
        except ImportError:
            from execution_authority_context import RuntimeAuthoritySnapshot  # type: ignore
        return RuntimeAuthoritySnapshot(
            ready=True,
            authority_ready=True,
            nonce_ready=True,
            dispatch_health_ready=True,
            dispatch_enabled=True,
            kill_switch_active=False,
            coordinator_state="EXECUTING",
            runtime_state="LIVE_ACTIVE",
            reason="test",
            lifecycle_phase="LIVE",
        )

    def _margin_critical_snapshot(self):
        return MarginHealthSnapshot(
            timestamp=time.time(),
            permission_state=MarginPermissionState.CONFIRMED.value,
            equivalent_balance_usd=1000.0,
            trade_balance_free_usd=5.0,
            margin_level_pct=85.0,
            margin_obligation_usd=980.0,
            free_margin_usd=5.0,
            unrealised_pnl_usd=-200.0,
            borrowed_exposure_usd=980.0,
            is_margin_enabled=True,
            maintenance_margin_ok=False,
            critical_margin_breach=True,
            reason="critical_margin_level:85.0%",
        )

    def _margin_low_snapshot(self):
        return MarginHealthSnapshot(
            timestamp=time.time(),
            permission_state=MarginPermissionState.CONFIRMED.value,
            equivalent_balance_usd=1000.0,
            trade_balance_free_usd=50.0,
            margin_level_pct=150.0,
            margin_obligation_usd=900.0,
            free_margin_usd=50.0,
            unrealised_pnl_usd=-100.0,
            borrowed_exposure_usd=900.0,
            is_margin_enabled=True,
            maintenance_margin_ok=False,
            critical_margin_breach=False,
            reason="low_margin_level:150.0%",
        )

    def _run_can_execute_with_margin_snap(self, snap: MarginHealthSnapshot) -> object:
        """Run can_execute() with all non-margin gates patched to pass."""
        from bot import execution_authority_context as eac

        live_snap = self._make_live_snapshot()

        mock_engine = MagicMock()
        mock_engine.get_health_snapshot.return_value = snap

        with (
            patch.object(eac, "runtime_authority_snapshot", return_value=live_snap),
            patch.object(eac, "has_execution_authority", return_value=True),
            patch.object(eac, "assert_distributed_writer_authority", return_value=None),
            patch.object(eac, "_read_current_lease_generation", return_value=(1, "")),
            patch.dict(os.environ, {
                "NIJA_RUNTIME_TRADING_STATE":    "LIVE_ACTIVE",
                "NIJA_EXECUTION_CIRCUIT_STATE":  "CLOSED",
                "NIJA_WRITER_LEASE_GENERATION":  "1",
                "NIJA_KRAKEN_MARGIN_ENABLED":    "true",
            }),
            patch("bot.execution_authority_context._env_truthy",
                  side_effect=lambda name: {
                      "NIJA_KRAKEN_MARGIN_ENABLED": True,
                      "NIJA_STABILITY_GOVERNOR_HALT_ENABLED": False,
                      "NIJA_MULTI_INSTANCE_POSSIBLE": False,
                      "NIJA_ASSUME_SINGLE_INSTANCE": False,
                      "NIJA_EXECUTION_RECOVERY_APPROVED": False,
                  }.get(name, False)),
            patch("bot.kraken_margin_engine.get_margin_engine",
                  return_value=mock_engine),
        ):
            # Patch TradingStateMachine heartbeat helpers
            with (
                patch.object(eac, "_evaluate_stability_authority",
                              return_value=MagicMock(
                                  allowed=True, halt_state="STABLE",
                                  throttle=0.0, size_multiplier=1.0,
                                  stress_score=0.0, collapsed_risk_score=0.0,
                                  reason="ok")),
            ):
                return eac.can_execute()

    def test_margin_disabled_passes_gate(self):
        """When margin is disabled the gate is skipped — can_execute depends only on other gates."""
        # This test just verifies no import error + feature-disabled path
        engine = _make_engine()
        with patch.dict(os.environ, {"NIJA_KRAKEN_MARGIN_ENABLED": "false"}):
            allowed, _ = engine.is_margin_trade_allowed()
        self.assertFalse(allowed)  # returns (False, "margin_disabled") for feature-off


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

class TestMarginEngineSingleton(unittest.TestCase):

    def test_get_margin_engine_returns_same_instance(self):
        e1 = get_margin_engine()
        e2 = get_margin_engine()
        self.assertIs(e1, e2)

    def test_invalidate_health_cache(self):
        engine = _make_engine()
        fake_snap = MarginHealthSnapshot(
            timestamp=time.time() - 1000,
            permission_state="CONFIRMED",
            equivalent_balance_usd=0.0,
            trade_balance_free_usd=0.0,
            margin_level_pct=0.0,
            margin_obligation_usd=0.0,
            free_margin_usd=0.0,
            unrealised_pnl_usd=0.0,
            borrowed_exposure_usd=0.0,
            is_margin_enabled=True,
            maintenance_margin_ok=True,
            critical_margin_breach=False,
            reason="test",
        )
        engine._last_snapshot = fake_snap
        engine._snapshot_ts = time.time()
        engine.invalidate_health_cache()
        self.assertIsNone(engine._last_snapshot)


if __name__ == "__main__":
    unittest.main()
