import unittest

from bot.broker_isolation_registry import BrokerIsolationRegistry
from bot.member_trading_activation import (
    ActivationEvidence,
    ActivationState,
    MemberTradingActivationManager,
)


def all_green(**overrides):
    values = {name: True for name in ActivationEvidence.__dataclass_fields__}
    values.update(overrides)
    return ActivationEvidence(**values)


class MemberTradingActivationTests(unittest.TestCase):
    def test_unpaid_member_fails_closed(self):
        manager = MemberTradingActivationManager(BrokerIsolationRegistry())
        result = manager.evaluate("user-1", "coinbase", "acct-1", all_green())
        self.assertEqual(result.state, ActivationState.PAYMENT_PENDING)
        self.assertFalse(result.trading_enabled)

    def test_verified_payment_auto_approves_member(self):
        manager = MemberTradingActivationManager(BrokerIsolationRegistry())
        result = manager.record_payment("user-1", "coinbase", "acct-1", verified=True)
        self.assertTrue(result.paid_member)
        self.assertTrue(result.member_approved)
        self.assertEqual(result.state, ActivationState.API_KEYS_REQUIRED)

    def test_paid_member_still_requires_credentials(self):
        manager = MemberTradingActivationManager(BrokerIsolationRegistry())
        manager.record_payment("user-1", "coinbase", "acct-1", verified=True)
        result = manager.evaluate("user-1", "coinbase", "acct-1", all_green(credentials_stored=False))
        self.assertEqual(result.state, ActivationState.API_KEYS_REQUIRED)
        self.assertFalse(result.trading_enabled)

    def test_missing_reconciliation_never_activates(self):
        manager = MemberTradingActivationManager(BrokerIsolationRegistry())
        manager.record_payment("user-1", "coinbase", "acct-1", verified=True)
        result = manager.activate("user-1", "coinbase", "acct-1", all_green(reconciliation_fresh=False))
        self.assertNotEqual(result.state, ActivationState.ACTIVE)
        self.assertFalse(result.trading_enabled)

    def test_kraken_requires_authoritative_positions_and_orders(self):
        manager = MemberTradingActivationManager(BrokerIsolationRegistry())
        manager.record_payment("user-1", "kraken", "acct-1", verified=True)
        result = manager.activate("user-1", "kraken", "acct-1", all_green(positions_authoritative=False))
        self.assertEqual(result.state, ActivationState.NOT_READY)
        self.assertFalse(result.trading_enabled)

    def test_halted_cell_blocks_member_activation(self):
        registry = BrokerIsolationRegistry()
        registry.halt_cell("coinbase", "test_halt")
        manager = MemberTradingActivationManager(registry)
        manager.record_payment("user-1", "coinbase", "acct-1", verified=True)
        result = manager.activate("user-1", "coinbase", "acct-1", all_green())
        self.assertEqual(result.state, ActivationState.HALTED)
        self.assertFalse(result.trading_enabled)

    def test_returned_state_is_immutable(self):
        manager = MemberTradingActivationManager(BrokerIsolationRegistry())
        result = manager.record_payment("user-1", "coinbase", "acct-1", verified=True)
        with self.assertRaises(Exception):
            result.trading_enabled = True
        self.assertFalse(manager.get_or_create("user-1", "coinbase", "acct-1").trading_enabled)

    def test_all_green_member_can_be_authorized(self):
        manager = MemberTradingActivationManager(BrokerIsolationRegistry())
        manager.record_payment("user-1", "coinbase", "acct-1", verified=True)
        result = manager.activate("user-1", "coinbase", "acct-1", all_green())
        self.assertEqual(result.state, ActivationState.ACTIVE)
        self.assertTrue(result.trading_enabled)


if __name__ == "__main__":
    unittest.main()
