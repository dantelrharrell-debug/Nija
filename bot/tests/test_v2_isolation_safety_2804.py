from __future__ import annotations

from bot.control.decision_context import UserDecisionContext, UserScopedIdempotencyRegistry
from bot.signal_broadcaster import SignalBroadcaster


def _ctx(**overrides):
    values = dict(
        user_id="user-a",
        account_id="acct-a",
        broker="kraken",
        portfolio_id="kraken:acct-a",
        strategy_signal_id="sig-1",
        trade_id="trade-1",
    )
    values.update(overrides)
    return UserDecisionContext(**values)


def test_idempotency_key_is_collision_safe_for_delimiter_ids():
    registry = UserScopedIdempotencyRegistry()
    a = registry.build_key(_ctx(user_id="a|b", account_id="c"), symbol="ETH-USD", direction="buy")
    b = registry.build_key(_ctx(user_id="a", account_id="b|c"), symbol="ETH-USD", direction="buy")
    assert a != b
    assert a.startswith("v2:")
    assert "user-a" not in a


def test_idempotency_key_binds_trade_identity():
    registry = UserScopedIdempotencyRegistry()
    a = registry.build_key(_ctx(trade_id="trade-1"), symbol="ETH-USD", direction="buy")
    b = registry.build_key(_ctx(trade_id="trade-2"), symbol="ETH-USD", direction="buy")
    assert a != b


class _KrakenBroker:
    broker_name = "kraken"
    user_id = "user-a"
    connected = True

    def __init__(self, proof=None):
        if proof is not None:
            self.kraken_margin_visibility_proven = proof

    def get_account_balance(self):
        return 1000.0

    def get_positions(self):
        return []

    def get_open_orders(self):
        return []


def test_kraken_margin_visibility_defaults_fail_closed():
    broadcaster = SignalBroadcaster()
    broadcaster.register_account("acct-a", _KrakenBroker(), balance=1000.0)
    decision = broadcaster.build_account_decisions(
        {"symbol": "ETH-USD", "strategy_signal_id": "sig-1", "strategy": "FIRST_CANDLE_ORB"}
    )[0]
    assert decision.portfolio_snapshot.metadata["kraken_margin_visibility_proven"] is False
    assert "AUTHORITATIVE_POSITION_UNPROVEN" in decision.portfolio_snapshot.readiness_notes(
        symbol="ETH-USD", direction="buy"
    )


def test_kraken_margin_visibility_requires_explicit_true():
    broadcaster = SignalBroadcaster()
    broadcaster.register_account("acct-a", _KrakenBroker(True), balance=1000.0)
    decision = broadcaster.build_account_decisions(
        {"symbol": "ETH-USD", "strategy_signal_id": "sig-1", "strategy": "FIRST_CANDLE_ORB"}
    )[0]
    assert decision.portfolio_snapshot.metadata["kraken_margin_visibility_proven"] is True


def test_pending_order_is_not_reported_as_filled(monkeypatch):
    import bot.signal_broadcaster as module

    broadcaster = SignalBroadcaster()
    broker = _KrakenBroker(True)
    broadcaster.register_account("acct-a", broker, balance=1000.0)
    monkeypatch.setattr(
        module,
        "submit_market_order_via_pipeline",
        lambda **kwargs: {"status": "pending", "order_id": "o-1"},
    )
    result = broadcaster._execute_single(
        broadcaster._accounts["acct-a"],
        {"symbol": "ETH-USD"},
        "ETH-USD",
        "buy",
        None,
    )
    assert result.status == "pending"
    assert result.status != "filled"
