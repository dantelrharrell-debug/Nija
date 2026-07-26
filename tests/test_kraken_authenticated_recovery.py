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
