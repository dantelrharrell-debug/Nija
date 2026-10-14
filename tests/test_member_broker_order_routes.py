"""Tests for account-bound routing, without real broker calls."""
import unittest

from bot.member_broker_cells import CellKey, CellState
from bot.member_broker_order_routes import OrderIntent, RouteDenied, validate_order_route


class OrderRouteTests(unittest.TestCase):
    def setUp(self):
        self.cell = CellKey("member1", "kraken", "live", "account1")
        self.intent = OrderIntent(self.cell, "member1", "account1", "unique_nonce_123")

    def route(self, intent=None, **overrides):
        values = dict(cell_status=CellState.READY, global_emergency_stop=False,
                      durable_nonce_reserved=True, broker_identity_attested=True, account_lease_fenced=True)
        values.update(overrides)
        return validate_order_route(intent or self.intent, **values)

    def test_valid_route_only_returns_cell_identifier(self):
        self.assertEqual(self.route(), self.cell.isolation_id)

    def test_cross_member_denied(self):
        with self.assertRaises(RouteDenied):
            self.route(OrderIntent(self.cell, "other", "account1", "unique_nonce_123"))

    def test_cross_broker_account_denied(self):
        with self.assertRaises(RouteDenied):
            self.route(OrderIntent(self.cell, "member1", "other", "unique_nonce_123"))

    def test_unready_cell_denied(self):
        with self.assertRaises(RouteDenied):
            self.route(cell_status=CellState.BLOCKED)

    def test_global_stop_denied(self):
        with self.assertRaises(RouteDenied):
            self.route(global_emergency_stop=True)

    def test_missing_durable_nonce_denied(self):
        with self.assertRaises(RouteDenied):
            self.route(durable_nonce_reserved=False)

    def test_unattested_broker_identity_denied(self):
        with self.assertRaises(RouteDenied):
            self.route(broker_identity_attested=False)

    def test_missing_account_lease_denied(self):
        with self.assertRaises(RouteDenied):
            self.route(account_lease_fenced=False)

    def test_malformed_nonce_denied(self):
        with self.assertRaises(RouteDenied):
            self.route(OrderIntent(self.cell, "member1", "account1", "bad key"))


if __name__ == "__main__":
    unittest.main()
