from __future__ import annotations

from types import SimpleNamespace

from bot import universal_broker_exit_supervisor_patch as guard


class Tracker:
    def __init__(self, positions):
        self.positions = positions
        self.closed = []

    def get_all_positions(self):
        return list(self.positions)

    def close_position(self, **kwargs):
        self.closed.append(kwargs)
        return True


class FakeKrakenBroker:
    broker_type = SimpleNamespace(value="kraken")

    def __init__(self, account_id, positions, market):
        self.account_id = account_id
        self.position_tracker = Tracker(positions)
        self.market = market
        self.orders = []

    def get_ticker(self, symbol):
        return {"last": self.market[symbol]}

    def place_market_order(self, **kwargs):
        self.orders.append(kwargs)
        return {"status": "filled", "order_id": f"order-{self.account_id}", "filled_price": self.market[kwargs["symbol"]]}


class FakeCoinbaseBroker(FakeKrakenBroker):
    broker_type = SimpleNamespace(value="coinbase")


class FakeOKXBroker(FakeKrakenBroker):
    broker_type = SimpleNamespace(value="okx")


def setup_function():
    guard._ACTIVE.clear()
    guard.auto_exit._HIGH_WATER.clear()


def test_platform_and_user_brokers_are_scanned_independently(monkeypatch):
    monkeypatch.setenv("NIJA_HARD_STOP_LOSS_PCT", "0.015")
    monkeypatch.setenv("NIJA_MAX_POSITION_LOSS_USD", "2.00")
    platform = FakeKrakenBroker(
        "platform",
        [{"symbol": "SOL-USD", "qty": 0.51389914, "entry_price": 81.99, "side": "long"}],
        {"SOL-USD": 76.45},
    )
    user = FakeKrakenBroker(
        "user:tania",
        [{"symbol": "ETH-USD", "qty": 0.04, "entry_price": 1800.0, "side": "long"}],
        {"ETH-USD": 1700.0},
    )

    assert guard._scan_broker(platform) == 1
    assert guard._scan_broker(user) == 1
    assert platform.orders[0]["side"] == "sell"
    assert user.orders[0]["side"] == "sell"


def test_fee_aware_profit_exit_works_for_every_supported_venue(monkeypatch):
    monkeypatch.setenv("NIJA_EXIT_ROUND_TRIP_FEE_PCT", "0.01")
    monkeypatch.setenv("NIJA_EXIT_SLIPPAGE_RESERVE_PCT", "0.001")
    monkeypatch.setenv("NIJA_MINIMUM_NET_PROFIT_PCT", "0.004")
    for cls in (FakeKrakenBroker, FakeCoinbaseBroker, FakeOKXBroker):
        broker = cls(
            f"platform:{cls.__name__}",
            [{"symbol": "ETH-USD", "quantity": 0.05, "entry_price": 100.0, "side": "long"}],
            {"ETH-USD": 102.0},
        )
        assert guard._scan_broker(broker) == 1
        assert broker.orders


def test_qty_alias_and_missing_side_are_protected(monkeypatch):
    monkeypatch.setenv("NIJA_HARD_STOP_LOSS_PCT", "0.015")
    broker = FakeCoinbaseBroker(
        "user:daivon",
        [{"symbol": "SOL-USD", "qty": 1.0, "entry_price": 100.0}],
        {"SOL-USD": 98.0},
    )
    assert guard._scan_broker(broker) == 1
    assert broker.orders[0]["side"] == "sell"


def test_unverified_cost_basis_does_not_submit_exit():
    broker = FakeOKXBroker(
        "platform",
        [{"symbol": "SOL-USDT", "qty": 1.0, "entry_price": 0.0}],
        {"SOL-USDT": 90.0},
    )
    assert guard._scan_broker(broker) == 0
    assert broker.orders == []


def test_broker_class_patch_registers_new_instances(monkeypatch):
    registered = []
    monkeypatch.setattr(guard, "_register_broker", lambda broker: registered.append(broker))
    module = SimpleNamespace(KrakenBroker=FakeKrakenBroker)
    assert guard._patch_module(module) is True
    broker = FakeKrakenBroker("platform", [], {})
    assert registered == [broker]
