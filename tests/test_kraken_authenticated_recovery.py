from __future__ import annotations

import importlib


def _module():
    return importlib.import_module("bot.canonical_broker_startup_convergence_v24")


def test_kraken_recovery_accepts_platform_credentials(monkeypatch):
    module = _module()
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "key")
    monkeypatch.setenv("KRAKEN_PLATFORM_API_SECRET", "secret")
    monkeypatch.delenv("KRAKEN_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_API_SECRET", raising=False)
    monkeypatch.delenv("NIJA_DISABLE_KRAKEN", raising=False)
    monkeypatch.delenv("KRAKEN_EXECUTION_DISABLED", raising=False)
    assert module._kraken_credentials_configured() is True


def test_kraken_recovery_accepts_canonical_aliases(monkeypatch):
    module = _module()
    monkeypatch.delenv("KRAKEN_PLATFORM_API_KEY", raising=False)
    monkeypatch.delenv("KRAKEN_PLATFORM_API_SECRET", raising=False)
    monkeypatch.setenv("KRAKEN_API_KEY", "key")
    monkeypatch.setenv("KRAKEN_API_SECRET", "secret")
    monkeypatch.delenv("NIJA_DISABLE_KRAKEN", raising=False)
    monkeypatch.delenv("KRAKEN_EXECUTION_DISABLED", raising=False)
    assert module._kraken_credentials_configured() is True


def test_kraken_recovery_respects_explicit_disable(monkeypatch):
    module = _module()
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "key")
    monkeypatch.setenv("KRAKEN_PLATFORM_API_SECRET", "secret")
    monkeypatch.setenv("NIJA_DISABLE_KRAKEN", "true")
    assert module._kraken_credentials_configured() is False


def test_resolve_registers_missing_canonical_kraken(monkeypatch):
    module = _module()
    broker_type = object()
    platform_account = object()

    class FakeKrakenBroker:
        def __init__(self, account_type):
            self.account_type = account_type
            self.connected = False

    class FakeManager:
        def __init__(self):
            self._platform_brokers = {}
            self.calls = []

        def register_platform_broker_instance(self, kind, broker, **kwargs):
            self.calls.append((kind, broker, kwargs))
            self._platform_brokers[kind] = broker
            return True

    broker_module = type(
        "BrokerModule",
        (),
        {
            "BrokerType": type("BrokerType", (), {"KRAKEN": broker_type}),
            "AccountType": type("AccountType", (), {"PLATFORM": platform_account}),
            "KrakenBroker": FakeKrakenBroker,
            "get_platform_broker": staticmethod(lambda _name: None),
        },
    )
    manager_module = type("ManagerModule", (), {})

    def fake_import(name):
        if name == "bot.broker_manager":
            return broker_module
        if name == "bot.multi_account_broker_manager":
            return manager_module
        raise AssertionError(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import)
    manager = FakeManager()
    broker, resolved_type, resolved_manager_module = (
        module._resolve_or_register_kraken_broker(manager)
    )

    assert isinstance(broker, FakeKrakenBroker)
    assert broker.account_type is platform_account
    assert resolved_type is broker_type
    assert resolved_manager_module is manager_module
    assert manager.calls[0][2] == {
        "mark_connected_state": False,
        "allow_recovery_registration": True,
    }


def test_bot_main_acquire_triggers_v24_manager_preparation(monkeypatch):
    module = _module()
    prepared = []

    class FakeV22:
        _ACQUIRE_WRAP_ATTR = "_fake_v22_acquire"

        @staticmethod
        def _patch_writer_acquire(_target):
            return True

        @staticmethod
        def _patch_main(_target):
            return True

    target = type("BotMain", (), {})()
    target.__name__ = "bot.bot_main"
    target._acquire_writer_authority_before_nonce = lambda: True
    target.main = lambda: 0

    monkeypatch.setattr(module, "_load_v22_module", lambda: FakeV22)
    monkeypatch.setattr(module, "_prepare_canonical_manager", lambda: prepared.append(True))

    assert module._patch_bot_main_module(target) is True
    assert target._acquire_writer_authority_before_nonce() is True
    assert prepared == [True]
    assert getattr(
        target._acquire_writer_authority_before_nonce,
        module._BOT_MAIN_ACQUIRE_WRAP_ATTR,
        False,
    ) is True
    assert getattr(target._acquire_writer_authority_before_nonce, FakeV22._ACQUIRE_WRAP_ATTR) is True



def test_coordinator_waits_for_writer_lineage_before_handoff(monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "_KRAKEN_RECOVERY_STARTED", False)
    monkeypatch.setattr(module, "_KRAKEN_RECOVERY_COORDINATOR_STARTED", False)
    monkeypatch.setattr(module, "_kraken_credentials_configured", lambda: True)
    monkeypatch.setenv("NIJA_KRAKEN_RECOVERY_COORDINATOR_INTERVAL_S", "5")
    monkeypatch.setenv("NIJA_KRAKEN_RECOVERY_COORDINATOR_WINDOW_S", "1800")

    lineage = iter(
        [
            (False, "fencing_token_missing"),
            (True, "lineage_ready generation=7"),
        ]
    )
    monkeypatch.setattr(module, "_writer_lineage", lambda: next(lineage))
    sleeps = []
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))
    prepared = []

    def prepare():
        prepared.append(True)
        module._KRAKEN_RECOVERY_STARTED = True
        return object()

    monkeypatch.setattr(module, "_prepare_canonical_manager", prepare)

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(module.threading, "Thread", ImmediateThread)

    assert module._start_kraken_recovery_coordinator() is True
    assert sleeps == [5.0]
    assert prepared == [True]


def test_authenticated_recovery_retries_transient_lineage_gap(monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "_KRAKEN_RECOVERY_STARTED", False)
    monkeypatch.setattr(module, "_kraken_credentials_configured", lambda: True)
    monkeypatch.setenv("NIJA_KRAKEN_RECOVERY_INTERVAL_S", "30")
    monkeypatch.setenv("NIJA_KRAKEN_RECOVERY_WINDOW_S", "1200")

    lineage = iter(
        [
            (False, "lease_generation_missing"),
            (True, "lineage_ready generation=8"),
        ]
    )
    monkeypatch.setattr(module, "_writer_lineage", lambda: next(lineage))
    sleeps = []
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    class Broker:
        connected = True

        @staticmethod
        def get_account_balance():
            return 25.0

    broker = Broker()
    broker_type = object()

    class ConnectionState:
        CONNECTED = object()

    manager_module = type(
        "ManagerModule",
        (),
        {"ConnectionState": ConnectionState},
    )
    broker_module = type(
        "BrokerModule",
        (),
        {
            "_KRAKEN_STARTUP_FSM": type(
                "FSM",
                (),
                {"is_connected": False, "is_connecting": False},
            )(),
            "register_platform_broker": staticmethod(
                lambda _name, _broker, connected: connected
            ),
        },
    )

    class Manager:
        def _transition_platform_state(self, _broker_type, _state):
            return None

        def on_broker_ready(self, _name, _balance_fn):
            return None

        def refresh_capital_authority(self, **_kwargs):
            return None

    manager = Manager()
    monkeypatch.setattr(
        module,
        "_resolve_or_register_kraken_broker",
        lambda _manager: (broker, broker_type, manager_module),
    )

    state_machine = type(
        "StateMachine",
        (),
        {"maybe_auto_activate": lambda self: None},
    )()
    state_module = type(
        "StateModule",
        (),
        {"get_state_machine": staticmethod(lambda: state_machine)},
    )

    def fake_import(name):
        if name == "bot.broker_manager":
            return broker_module
        if name == "bot.trading_state_machine":
            return state_module
        raise AssertionError(name)

    monkeypatch.setattr(module.importlib, "import_module", fake_import)

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(module.threading, "Thread", ImmediateThread)

    assert module._start_kraken_authenticated_recovery(manager) is True
    assert sleeps == [30.0]
    assert module.os.environ["NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY"] == "1"


def test_kraken_permission_retry_reenables_detailed_logging(monkeypatch):
    from bot.broker_manager import KrakenBroker

    KrakenBroker._permission_error_details_logged = True
    KrakenBroker._permission_failed_accounts = {"PLATFORM"}

    broker = object.__new__(KrakenBroker)
    broker.account_type = KrakenBroker.__mro__[1].__dict__.get("account_type", None)
    broker.user_id = None
    broker.connected = False
    broker._hard_stopped = False
    broker._hard_stop_reason = ""
    broker.register_broker = lambda *_args, **_kwargs: None

    try:
        from bot.broker_manager import AccountType, _KRAKEN_STARTUP_FSM
        broker.account_type = AccountType.PLATFORM
        _KRAKEN_STARTUP_FSM.begin_platform_boot = lambda: None
    except Exception:
        pass

    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "key")
    monkeypatch.setenv("KRAKEN_PLATFORM_API_SECRET", "secret")
    monkeypatch.delenv("NIJA_KRAKEN_GATEWAY_ONLY", raising=False)
    monkeypatch.setattr("bot.broker_manager.os.getenv", __import__("os").getenv)

    class StopAfterCacheClear(Exception):
        pass

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "krakenex":
            raise StopAfterCacheClear()
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    try:
        broker.connect()
    except StopAfterCacheClear:
        pass

    assert "PLATFORM" not in KrakenBroker._permission_failed_accounts
    assert KrakenBroker._permission_error_details_logged is False
