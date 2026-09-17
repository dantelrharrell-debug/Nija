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


def test_unpaid_member_fails_closed():
    manager = MemberTradingActivationManager()
    result = manager.evaluate("user-1", "coinbase", "acct-1", all_green())
    assert result.state == ActivationState.PAYMENT_PENDING
    assert not result.trading_enabled


def test_paid_member_still_requires_credentials():
    manager = MemberTradingActivationManager()
    manager.record_payment("user-1", "coinbase", "acct-1", verified=True)
    result = manager.evaluate("user-1", "coinbase", "acct-1", all_green(credentials_stored=False))
    assert result.state == ActivationState.API_KEYS_REQUIRED
    assert not result.trading_enabled


def test_missing_reconciliation_never_activates():
    manager = MemberTradingActivationManager()
    manager.record_payment("user-1", "coinbase", "acct-1", verified=True)
    result = manager.activate("user-1", "coinbase", "acct-1", all_green(reconciliation_fresh=False))
    assert result.state != ActivationState.ACTIVE
    assert not result.trading_enabled


def test_kraken_requires_authoritative_positions_and_orders():
    manager = MemberTradingActivationManager()
    manager.record_payment("user-1", "kraken", "acct-1", verified=True)
    result = manager.activate("user-1", "kraken", "acct-1", all_green(positions_authoritative=False))
    assert result.state == ActivationState.NOT_READY
    assert not result.trading_enabled


def test_halted_cell_blocks_member_activation():
    registry = BrokerIsolationRegistry()
    registry.halt_cell("coinbase", "test_halt")
    manager = MemberTradingActivationManager(registry)
    manager.record_payment("user-1", "coinbase", "acct-1", verified=True)
    result = manager.activate("user-1", "coinbase", "acct-1", all_green())
    assert result.state == ActivationState.HALTED
    assert not result.trading_enabled


def test_all_green_member_can_be_authorized():
    manager = MemberTradingActivationManager()
    manager.record_payment("user-1", "coinbase", "acct-1", verified=True)
    result = manager.activate("user-1", "coinbase", "acct-1", all_green())
    assert result.state == ActivationState.ACTIVE
    assert result.trading_enabled
