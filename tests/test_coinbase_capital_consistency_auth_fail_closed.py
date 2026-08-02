from __future__ import annotations

import importlib
import sys


def _module():
    return importlib.import_module("bot.coinbase_capital_consistency_patch")


def _seed_ready_environment(monkeypatch):
    monkeypatch.setenv("NIJA_COINBASE_CONNECTED", "1")
    monkeypatch.setenv("NIJA_COINBASE_BALANCE_OBSERVED", "1")
    monkeypatch.setenv("NIJA_COINBASE_SPENDABLE_QUOTE", "200.21")
    monkeypatch.setenv("NIJA_COINBASE_TRADING_READY", "1")
    monkeypatch.setenv("NIJA_COINBASE_ACTIVATED", "1")
    monkeypatch.setenv("NIJA_COINBASE_ACTIVATION_STATE", "ready")
    monkeypatch.setenv("NIJA_COINBASE_FUNDING_STATUS", "funded")


def test_cached_balance_cannot_restore_readiness_after_401(monkeypatch):
    module = _module()
    _seed_ready_environment(monkeypatch)

    class Broker:
        connected = True
        _auth_failed = True
        _is_available = True
        exit_only_mode = False
        _last_known_balance = 200.21

        def get_account_balance(self):
            return self._last_known_balance

    wrapped = module._wrap_balance(
        Broker,
        "get_account_balance",
        Broker.get_account_balance,
    )
    broker = Broker()

    assert wrapped(broker) == 0.0
    assert broker.connected is False
    assert broker._is_available is False
    assert broker.exit_only_mode is True
    assert module.os.environ["NIJA_COINBASE_CONNECTED"] == "0"
    assert module.os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] == "0"
    assert module.os.environ["NIJA_COINBASE_SPENDABLE_QUOTE"] == "0"
    assert module.os.environ["NIJA_COINBASE_TRADING_READY"] == "0"
    assert module.os.environ["NIJA_COINBASE_ACTIVATED"] == "0"
    assert (
        module.os.environ["NIJA_COINBASE_ACTIVATION_STATE"]
        == "authentication_failed"
    )


def test_adapter_detects_nested_broker_auth_failure(monkeypatch):
    module = _module()
    _seed_ready_environment(monkeypatch)

    class CanonicalBroker:
        connected = True
        _auth_failed = True
        _last_known_balance = 90.0

    class Adapter:
        connected = True

        def __init__(self):
            self._broker = CanonicalBroker()

        def connect(self):
            return True

    wrapped = module._wrap_connect(Adapter, Adapter.connect)
    adapter = Adapter()

    assert wrapped(adapter) is False
    assert adapter.connected is False
    assert adapter._broker.connected is False
    assert module.os.environ["NIJA_COINBASE_TRADING_READY"] == "0"
    assert module.os.environ["NIJA_COINBASE_AUTH_STATE"] == "authentication_failed"


def test_capital_wrapper_patch_is_chain_aware():
    module = _module()

    class Broker:
        connected = False

        def connect(self):
            return False

        def get_account_balance(self):
            return 0.0

    assert module._patch_class(Broker) is True
    first_connect = Broker.connect
    first_balance = Broker.get_account_balance

    assert module._patch_class(Broker) is False
    assert Broker.connect is first_connect
    assert Broker.get_account_balance is first_balance


def test_install_is_process_wide_idempotent_across_module_aliases(
    monkeypatch, caplog
):
    module = _module()
    state = module._STATE
    original_started = state["monitor_started"]
    original_attested = state["install_attested"]
    started = []

    class FakeThread:
        def __init__(self, **kwargs):
            started.append(kwargs)

        def start(self):
            return None

    alias_name = "nija_test_coinbase_capital_consistency_alias"
    try:
        state["monitor_started"] = False
        state["install_attested"] = False
        monkeypatch.setattr(module.threading, "Thread", FakeThread)
        monkeypatch.setattr(module, "_patch_loaded", lambda: False)
        caplog.clear()
        caplog.set_level(module.logging.CRITICAL)

        spec = importlib.util.spec_from_file_location(alias_name, module.__file__)
        assert spec is not None
        assert spec.loader is not None
        alias = importlib.util.module_from_spec(spec)
        sys.modules[alias_name] = alias
        spec.loader.exec_module(alias)

        assert module.install() is True
        records = [
            record
            for record in caplog.records
            if "COINBASE_CAPITAL_CONSISTENCY_INSTALLED" in record.getMessage()
        ]
        assert len(started) == 1
        assert len(records) == 1
        assert state["monitor_started"] is True
        assert state["install_attested"] is True
    finally:
        sys.modules.pop(alias_name, None)
        state["monitor_started"] = original_started
        state["install_attested"] = original_attested
