#!/usr/bin/env python3
"""
Tests for emergency_reset module and the platform hierarchy fix
in capital_tier_hierarchy.

Validates:
  - Platform accounts always receive BALLER tier in CapitalTierHierarchy
  - Convenience functions (get_max_positions_for_balance, etc.) pass is_platform through
  - emergency_reset.delete_position_files removes existing files
  - emergency_reset.stop_bot activates the kill switch
  - run_emergency_reset orchestrates all steps in correct order
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, call

# ── Path setup ───────────────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, 'bot'))


# =============================================================================
# Platform Hierarchy Tests
# =============================================================================

class TestPlatformHierarchyFix(unittest.TestCase):
    """
    Verify that CapitalTierHierarchy respects the is_platform flag, returning
    BALLER tier regardless of balance — matching tier_config.py behaviour.
    """

    def setUp(self):
        from capital_tier_hierarchy import CapitalTierHierarchy, CapitalTier
        self.hierarchy = CapitalTierHierarchy()
        self.CapitalTier = CapitalTier

    def test_platform_small_balance_returns_baller(self):
        """A platform account with a tiny balance must still be BALLER."""
        tier = self.hierarchy.get_tier_from_balance(50.0, is_platform=True)
        self.assertEqual(tier, self.CapitalTier.BALLER)

    def test_platform_medium_balance_returns_baller(self):
        """A platform account with a mid-range balance must still be BALLER."""
        tier = self.hierarchy.get_tier_from_balance(500.0, is_platform=True)
        self.assertEqual(tier, self.CapitalTier.BALLER)

    def test_platform_large_balance_returns_baller(self):
        """A platform account with a large balance must still be BALLER."""
        tier = self.hierarchy.get_tier_from_balance(25000.0, is_platform=True)
        self.assertEqual(tier, self.CapitalTier.BALLER)

    def test_non_platform_small_balance_returns_starter(self):
        """A non-platform account with $75 should be STARTER, not BALLER."""
        tier = self.hierarchy.get_tier_from_balance(75.0, is_platform=False)
        self.assertEqual(tier, self.CapitalTier.STARTER)

    def test_non_platform_large_balance_returns_baller(self):
        """A non-platform account with $50k balance should be BALLER by balance."""
        tier = self.hierarchy.get_tier_from_balance(50000.0, is_platform=False)
        self.assertEqual(tier, self.CapitalTier.BALLER)

    def test_get_max_positions_platform_flag(self):
        """Platform accounts should get BALLER-tier max positions even with $50."""
        from capital_tier_hierarchy import TIER_POSITION_RULES, CapitalTier
        baller_max = TIER_POSITION_RULES[CapitalTier.BALLER].max_positions
        platform_max = self.hierarchy.get_max_positions(50.0, is_platform=True)
        self.assertEqual(platform_max, baller_max)

    def test_get_optimal_positions_platform_flag(self):
        """Platform accounts should get BALLER-tier max_positions even with $50."""
        from capital_tier_hierarchy import TIER_POSITION_RULES, CapitalTier
        # The key benefit: platform gets BALLER max_positions (15), not STARTER max (2)
        baller_max = TIER_POSITION_RULES[CapitalTier.BALLER].max_positions
        starter_max = TIER_POSITION_RULES[CapitalTier.STARTER].max_positions
        platform_max = self.hierarchy.get_max_positions(50.0, is_platform=True)
        # Platform must get BALLER max, which is much higher than STARTER max
        self.assertEqual(platform_max, baller_max)
        self.assertGreater(baller_max, starter_max)

    def test_validate_new_position_platform_flag(self):
        """Platform accounts should not be blocked by STARTER max_positions cap."""
        # Use a balance and position size that satisfies BALLER tier minimums
        # BALLER: min_position_size_usd=$100, max_positions=15
        result = self.hierarchy.validate_new_position(
            balance=25000.0,
            current_position_count=5,
            proposed_size_usd=500.0,
            is_platform=True,
        )
        is_valid, code, message = result
        # BALLER (15 positions), we have 5 — should be approved
        self.assertTrue(is_valid, f"Platform entry unexpectedly rejected: {message}")

    def test_validate_new_position_non_platform_blocked_by_starter_cap(self):
        """Non-platform with $75 balance hits STARTER max_positions cap."""
        # STARTER: max_positions=2, so 2 existing positions blocks entry
        result = self.hierarchy.validate_new_position(
            balance=75.0,
            current_position_count=2,
            proposed_size_usd=30.0,
            is_platform=False,
        )
        is_valid, code, message = result
        self.assertFalse(is_valid)
        self.assertEqual(code, "TIER_MAX_POSITIONS")

    def test_convenience_get_max_positions_for_balance(self):
        """Convenience function must forward is_platform flag."""
        from capital_tier_hierarchy import (
            get_max_positions_for_balance,
            TIER_POSITION_RULES,
            CapitalTier,
        )
        baller_max = TIER_POSITION_RULES[CapitalTier.BALLER].max_positions
        result = get_max_positions_for_balance(75.0, is_platform=True)
        self.assertEqual(result, baller_max)

    def test_convenience_validate_position_entry(self):
        """validate_position_entry convenience function must forward is_platform."""
        from capital_tier_hierarchy import validate_position_entry
        # Use BALLER-compatible values: $25k balance, $500 position
        is_valid, code, message = validate_position_entry(
            balance=25000.0,
            current_positions=5,
            size_usd=500.0,
            is_platform=True,
        )
        self.assertTrue(is_valid, f"Expected APPROVED for platform account, got: {message}")

    def test_update_balance_with_platform_flag(self):
        """update_balance should store BALLER tier when is_platform=True."""
        self.hierarchy.update_balance(75.0, is_platform=True)
        self.assertEqual(self.hierarchy.current_tier, self.CapitalTier.BALLER)

    def test_update_balance_without_platform_flag(self):
        """update_balance should store STARTER tier for $75 non-platform account."""
        self.hierarchy.update_balance(75.0, is_platform=False)
        self.assertEqual(self.hierarchy.current_tier, self.CapitalTier.STARTER)


# =============================================================================
# Emergency Reset Tests
# =============================================================================

class TestDeletePositionFiles(unittest.TestCase):
    """Tests for emergency_reset.delete_position_files."""

    def test_deletes_existing_positions_json(self):
        from emergency_reset import delete_position_files

        with tempfile.NamedTemporaryFile(
            suffix='.json', delete=False, mode='w'
        ) as fh:
            json.dump({'positions': {}}, fh)
            tmp_path = fh.name

        try:
            deleted = delete_position_files(extra_paths=[tmp_path])
            self.assertIn(tmp_path, deleted)
            self.assertFalse(os.path.exists(tmp_path))
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_no_error_when_files_absent(self):
        from emergency_reset import delete_position_files

        # Should complete without raising
        deleted = delete_position_files(extra_paths=['/tmp/nija_nonexistent_positions.json'])
        self.assertEqual(deleted, [])

    def test_deletes_multiple_files(self):
        from emergency_reset import delete_position_files

        tmp_files = []
        for _ in range(3):
            fh = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w')
            json.dump({}, fh)
            fh.close()
            tmp_files.append(fh.name)

        try:
            deleted = delete_position_files(extra_paths=tmp_files)
            self.assertEqual(len(deleted), 3)
            for path in tmp_files:
                self.assertFalse(os.path.exists(path))
        finally:
            for path in tmp_files:
                if os.path.exists(path):
                    os.remove(path)


class TestStopBot(unittest.TestCase):
    """Tests for emergency_reset.stop_bot."""

    def test_activates_kill_switch(self):
        mock_ks = MagicMock()
        mock_ks.is_active.return_value = False

        with patch('emergency_reset.get_kill_switch', return_value=mock_ks):
            from emergency_reset import stop_bot
            result = stop_bot("unit test")

        self.assertTrue(result)
        mock_ks.activate.assert_called_once()

    def test_returns_true_when_already_active(self):
        mock_ks = MagicMock()
        mock_ks.is_active.return_value = True

        with patch('emergency_reset.get_kill_switch', return_value=mock_ks):
            from emergency_reset import stop_bot
            result = stop_bot("already active")

        self.assertTrue(result)
        mock_ks.activate.assert_not_called()


class TestCancelAllOpenOrders(unittest.TestCase):
    """Tests for emergency_reset.cancel_all_open_orders."""

    def test_coinbase_orders_cancelled(self):
        from emergency_reset import cancel_all_open_orders

        mock_order = MagicMock()
        mock_order.order_id = 'ORDER-123'

        mock_client = MagicMock()
        mock_client.list_orders.return_value = MagicMock(orders=[mock_order])

        mock_broker = MagicMock()
        mock_broker.client = mock_client
        type(mock_broker).__name__ = 'CoinbaseBroker'

        results = cancel_all_open_orders([mock_broker])
        # cancel_orders should have been called
        mock_client.cancel_orders.assert_called_once_with(order_ids=['ORDER-123'])

    def test_no_brokers_returns_empty(self):
        from emergency_reset import cancel_all_open_orders
        results = cancel_all_open_orders([])
        self.assertEqual(results, {})


class TestLiquidateAllPositions(unittest.TestCase):
    """Tests for emergency_reset.liquidate_all_positions."""

    def test_liquidates_using_force_liquidate(self):
        from emergency_reset import liquidate_all_positions

        mock_broker = MagicMock()
        mock_broker.broker_type = 'coinbase'
        mock_broker.get_positions.return_value = [
            {'symbol': 'BTC-USD', 'quantity': 0.01}
        ]
        mock_broker.force_liquidate.return_value = {'status': 'filled'}

        results = liquidate_all_positions([mock_broker])
        mock_broker.force_liquidate.assert_called_once_with(
            symbol='BTC-USD',
            quantity=0.01,
            reason='Emergency reset liquidation',
        )
        self.assertEqual(results.get('coinbase', results.get(str(mock_broker.broker_type))), 1)

    def test_no_positions_returns_zero(self):
        from emergency_reset import liquidate_all_positions

        mock_broker = MagicMock()
        mock_broker.broker_type = 'coinbase'
        mock_broker.get_positions.return_value = []

        results = liquidate_all_positions([mock_broker])
        mock_broker.force_liquidate.assert_not_called()


class TestRunEmergencyReset(unittest.TestCase):
    """Integration test for run_emergency_reset orchestrator."""

    def test_all_steps_called_in_order(self):
        """Verify each step is invoked and summary keys are populated."""
        import emergency_reset as er

        calls = []

        def mock_stop_bot(reason):
            calls.append('stop_bot')
            return True

        def mock_cancel(brokers):
            calls.append('cancel')
            return {'mock': 0}

        def mock_liquidate(brokers):
            calls.append('liquidate')
            return {'mock': 0}

        def mock_dust(brokers, dust_threshold_usd):
            calls.append('dust')
            return {'mock': 0}

        def mock_delete(extra_paths):
            calls.append('delete')
            return []

        with patch.object(er, 'stop_bot', side_effect=mock_stop_bot), \
             patch.object(er, 'cancel_all_open_orders', side_effect=mock_cancel), \
             patch.object(er, 'liquidate_all_positions', side_effect=mock_liquidate), \
             patch.object(er, 'sweep_dust', side_effect=mock_dust), \
             patch.object(er, 'delete_position_files', side_effect=mock_delete), \
             patch('time.sleep'):  # skip delays in tests

            summary = er.run_emergency_reset(brokers=[MagicMock()])

        self.assertEqual(calls, ['stop_bot', 'cancel', 'liquidate', 'dust', 'delete'])
        self.assertIn('kill_switch_activated', summary)
        self.assertIn('orders_cancelled', summary)
        self.assertIn('positions_liquidated', summary)
        self.assertIn('dust_swept', summary)
        self.assertIn('files_deleted', summary)
        self.assertIn('completed_at', summary)

    def test_no_brokers_skips_broker_steps(self):
        """With no brokers, only kill switch and file deletion should execute."""
        import emergency_reset as er

        calls = []

        with patch.object(er, 'stop_bot', side_effect=lambda r: calls.append('stop_bot') or True), \
             patch.object(er, 'cancel_all_open_orders', side_effect=lambda b: calls.append('cancel') or {}), \
             patch.object(er, 'liquidate_all_positions', side_effect=lambda b: calls.append('liquidate') or {}), \
             patch.object(er, 'sweep_dust', side_effect=lambda b, d: calls.append('dust') or {}), \
             patch.object(er, 'delete_position_files', side_effect=lambda e: calls.append('delete') or []):

            er.run_emergency_reset(brokers=None)

        # Broker-dependent steps should not be called (no brokers)
        self.assertIn('stop_bot', calls)
        self.assertIn('delete', calls)
        self.assertNotIn('cancel', calls)
        self.assertNotIn('liquidate', calls)
        self.assertNotIn('dust', calls)


if __name__ == '__main__':
    unittest.main(verbosity=2)
