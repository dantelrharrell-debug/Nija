from __future__ import annotations

from types import SimpleNamespace

import account_exit_management_recovery_patch as patch


class BrokerType:
    def __init__(self, value):
        self.value = value


class Broker:
    def __init__(self, connected=True, balance=0.0, positions=None, orders=None):
        self.connected = connected
        self.balance = balance
        self.positions = list(positions or [])
        self.orders = list(orders or [])
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        self.connected = True
        return True

    def get_account_balance(self):
        return self.balance

    def get_positions(self):
        return list(self.positions)

    def get_open_orders(self):
        return list(self.orders)


class Strategy:
    def __init__(self):
        self.adoptions = []
        self.cycles = []

    def adopt_existing_positions(self, **kwargs):
        broker = kwargs["broker"]
        self.adoptions.append(kwargs["account_id"])
        return {
            "success": True,
            "positions_found": len(broker.positions),
            "positions_adopted": len(broker.positions),
            "open_orders_count": len(broker.orders),
        }

    def run_cycle(self, broker=None, user_mode=False):
        self.cycles.append((broker, user_mode))
        return 15


class Manager:
    def __init__(self, platform, users, configs):
        self.platform_brokers = platform
        self.user_brokers = users
        self.user_configs = configs
        self.connect_users_calls = 0

    def connect_users_from_config(self):
        self.connect_users_calls += 1


class Trader:
    def __init__(self, manager, strategy):
        self.multi_account_manager = manager
        self.broker_manager = None
        self.trading_strategy = strategy
        self.broker_threads = {}
        self.user_broker_threads = {}
        self.stop_flags = {}
        self.user_stop_flags = {}
        self.normal_platform_started = []
        self.normal_users_started = []

    def _get_platform_broker_source(self):
        return self.multi_account_manager.platform_brokers

    def _get_broker_balance(self, broker, broker_type, label):
        return broker.get_account_balance()

    def _start_platform_thread(self, broker_type, broker):
        self.normal_platform_started.append(broker_type.value)

    def _start_user_thread(self, user_id, broker_type, broker):
        self.normal_users_started.append((user_id, broker_type.value))

    def should_start_user_independent_thread(self, user_id):
        cfg = self.multi_account_manager.user_configs[user_id]
        return bool(cfg.independent_trading)


def config(active=True, independent=True):
    return SimpleNamespace(active_trading=active, independent_trading=independent)


def test_user_reconnect_does_not_wait_for_platform(monkeypatch):
    platform = Broker(connected=False, balance=100)
    user = Broker(connected=False, balance=50)
    manager = Manager(
        {BrokerType("kraken"): platform},
        {"daivon": {BrokerType("kraken"): user}},
        {"daivon": config(active=True, independent=True)},
    )
    trader = Trader(manager, Strategy())
    monkeypatch.setattr(patch, "_ensure_exit_thread", lambda *args, **kwargs: False)

    class C:
        pass

    C._retry_user_connections = lambda self: None
    C.start_independent_trading = lambda self: True
    patch._patch_class(C)
    C._retry_user_connections(trader)

    assert manager.connect_users_calls == 1
    assert user.connected is True
    assert ("daivon", "kraken") in trader.normal_users_started


def test_copy_or_recovery_user_gets_exit_only_thread(monkeypatch):
    user = Broker(connected=True, balance=50, positions=[{"symbol": "ETH-USD", "quantity": 1}])
    manager = Manager({}, {"tania": {BrokerType("kraken"): user}}, {"tania": config(active=False, independent=False)})
    trader = Trader(manager, Strategy())
    calls = []
    monkeypatch.setattr(patch, "_ensure_exit_thread", lambda *args: calls.append(args[1]) or True)

    patch._retry_all_accounts(trader)

    assert trader.normal_users_started == []
    assert calls == ["user:tania:kraken"]


def test_underfunded_platform_with_position_gets_exit_only(monkeypatch):
    platform = Broker(connected=True, balance=0.0, positions=[{"symbol": "ADA-USD", "quantity": 10}])
    manager = Manager({BrokerType("kraken"): platform}, {}, {})
    trader = Trader(manager, Strategy())
    calls = []
    monkeypatch.setattr(patch, "_ensure_exit_thread", lambda *args: calls.append(args[1]) or True)

    patch._retry_all_accounts(trader)

    assert trader.normal_platform_started == []
    assert calls == ["platform:kraken"]


def test_exit_management_runs_phase2_only(monkeypatch):
    broker = Broker(connected=True, positions=[{"symbol": "SOL-USD", "quantity": 2}])
    strategy = Strategy()
    manager = Manager({}, {}, {})
    trader = Trader(manager, strategy)
    monkeypatch.setitem(
        __import__("sys").modules,
        "bot.startup_position_sync",
        SimpleNamespace(sync_exchange_positions_on_startup=lambda strategy: 1),
    )

    positions, orders = patch._adopt_and_manage(trader, "user:daivon:kraken", broker)

    assert positions == 1
    assert orders == 0
    assert strategy.cycles == [(broker, True)]


def test_no_position_no_order_does_not_run_cycle():
    broker = Broker(connected=True)
    strategy = Strategy()
    trader = Trader(Manager({}, {}, {}), strategy)

    positions, orders = patch._adopt_and_manage(trader, "platform:kraken", broker)

    assert (positions, orders) == (0, 0)
    assert strategy.cycles == []


def test_normal_thread_prevents_duplicate_exit_thread():
    broker = Broker(connected=True, positions=[{"symbol": "BTC-USD", "quantity": 1}])
    bt = BrokerType("kraken")
    trader = Trader(Manager({bt: broker}, {}, {}), Strategy())
    alive = SimpleNamespace(is_alive=lambda: True)
    trader.broker_threads["kraken"] = alive

    started = patch._ensure_exit_thread(trader, "platform:kraken", "platform", None, bt, broker)

    assert started is False


def test_adoption_verification_resolves_exact_account_broker():
    class T:
        def __init__(self):
            self.checked = []

        def adopt_existing_positions(self, broker, broker_name="", account_id=""):
            return {"success": True, "positions_found": 1, "positions_adopted": 1}

        def verify_position_adoption_status(self, broker, broker_name="", account_id=""):
            self.checked.append((broker, broker_name, account_id))
            return broker is not None

    patch._patch_strategy_class(T)
    strategy = T()
    exact = Broker(connected=True, positions=[{"symbol": "ETH-USD", "quantity": 1}])
    strategy.adopt_existing_positions(exact, broker_name="daivon_kraken", account_id="USER_DAIVON_KRAKEN")

    assert strategy.verify_position_adoption_status(
        broker_name="daivon_kraken",
        account_id="USER_DAIVON_KRAKEN",
    ) is True
    assert strategy.checked == [(exact, "daivon_kraken", "USER_DAIVON_KRAKEN")]


def test_funded_normal_account_gets_immediate_exit_evaluation(monkeypatch):
    platform = Broker(connected=True, balance=100.0, positions=[{"symbol": "ADA-USD", "quantity": 5}])
    bt = BrokerType("kraken")
    trader = Trader(Manager({bt: platform}, {}, {}), Strategy())
    managed = []
    monkeypatch.setattr(patch, "_adopt_and_manage", lambda *args: managed.append(args[1]) or (1, 0))

    patch._start_normal_or_exit(trader, "platform:kraken", "platform", None, bt, platform)

    assert managed == ["platform:kraken"]
    assert trader.normal_platform_started == ["kraken"]
