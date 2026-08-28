import os
import types

import bot.runtime_terminal_activation_liveness_v255_patch as v255


class _Broker:
    def __init__(self, name: str):
        self.name = name


class _Strategy:
    def __init__(self):
        self.brokers = {
            "kraken": _Broker("kraken"),
            "coinbase": _Broker("coinbase"),
        }
        self.calls = []
        self.multi_account_manager = types.SimpleNamespace(platform_brokers=dict(self.brokers))
        self.broker_manager = None
        self.broker = None

    def _broker_key_from_obj(self, broker):
        return broker.name

    def _heartbeat_auth_verify(self, broker):
        self.calls.append(("auth", broker.name))
        if broker.name == "kraken":
            return False, "get_account_balance:Kraken read lock busy after 3.00s for Balance"
        return True, "get_account_balance"

    def _get_heartbeat_broker(self):
        ready = tuple(
            name for name in os.environ.get("NIJA_EXECUTION_READY_VENUES", "").split(",") if name
        )
        self.calls.append(("select", ready))
        selected = self.brokers.get(ready[0]) if ready else None
        self.broker = selected
        return selected

    def _select_entry_broker(self, candidates):
        for name in ("kraken", "coinbase"):
            for broker in candidates.values():
                if broker.name == name:
                    return broker, name, {name: "ready"}
        return None, None, {}

    def _execute_heartbeat_trade(self):
        broker = self._get_heartbeat_broker()
        if broker is None:
            return False
        ok, _detail = self._heartbeat_auth_verify(broker)
        return bool(ok)


def test_heartbeat_local_contention_fails_over_only_to_ready_venue(monkeypatch):
    trading = types.SimpleNamespace(TradingStrategy=_Strategy)
    original_import = v255.importlib.import_module

    def fake_import(name):
        if name == "bot.trading_strategy":
            return trading
        return original_import(name)

    monkeypatch.setattr(v255.importlib, "import_module", fake_import)
    monkeypatch.setenv("NIJA_EXECUTION_READY_VENUES", "kraken,coinbase")

    assert v255._patch_trading_strategy() is True
    strategy = _Strategy()
    assert strategy._execute_heartbeat_trade() is True
    assert ("auth", "kraken") in strategy.calls
    assert ("auth", "coinbase") in strategy.calls
    assert os.environ["NIJA_EXECUTION_READY_VENUES"] == "kraken,coinbase"


def test_non_local_auth_failure_does_not_fail_over(monkeypatch):
    class Strategy(_Strategy):
        def _heartbeat_auth_verify(self, broker):
            self.calls.append(("auth", broker.name))
            return False, "EAPI:Invalid key"

    trading = types.SimpleNamespace(TradingStrategy=Strategy)
    original_import = v255.importlib.import_module

    def fake_import(name):
        if name == "bot.trading_strategy":
            return trading
        return original_import(name)

    monkeypatch.setattr(v255.importlib, "import_module", fake_import)
    monkeypatch.setenv("NIJA_EXECUTION_READY_VENUES", "kraken,coinbase")

    assert v255._patch_trading_strategy() is True
    strategy = Strategy()
    assert strategy._execute_heartbeat_trade() is False
    assert strategy.calls.count(("auth", "kraken")) == 1
    assert ("auth", "coinbase") not in strategy.calls


def test_bootstrap_non_owner_transition_is_deferred():
    class FSM:
        def __init__(self):
            self.owner = False
            self.state = types.SimpleNamespace(value="PLATFORM_READY")
            self.transition_calls = 0

        def is_owner_thread(self):
            return self.owner

        def transition(self, *_args, **_kwargs):
            self.transition_calls += 1
            return True

    target = FSM()
    proxy = v255._OwnerAwareBootstrapFSMProxy(target)
    assert proxy.transition("BALANCE_HYDRATED") is False
    assert target.transition_calls == 0

    target.owner = True
    assert proxy.transition("BALANCE_HYDRATED") is True
    assert target.transition_calls == 1


def test_position_worker_never_synthesizes_fetch_proof(monkeypatch):
    calls = []

    class Broker:
        _startup_position_sync_adopted = True
        _startup_position_sync_fetch_ok = False

    broker = Broker()

    def original_worker(manager, broker_name, broker_obj, key, trigger):
        calls.append(("worker", broker_name, trigger))
        broker_obj._startup_position_sync_adopted = True
        broker_obj._startup_position_sync_fetch_ok = False

    v108 = types.SimpleNamespace(
        _worker=original_worker,
        _publish_readiness=lambda manager, source: calls.append(("publish", source)),
    )
    v163 = types.SimpleNamespace(install=lambda: True)
    v182 = types.SimpleNamespace(install=lambda: True)

    def fake_import(name):
        mapping = {
            "bot.runtime_activation_convergence_v163_patch": v163,
            "bot.runtime_position_fetch_proof_v182_patch": v182,
            "bot.platform_position_sync_v108_patch": v108,
        }
        return mapping[name]

    monkeypatch.setattr(v255.importlib, "import_module", fake_import)
    assert v255._patch_position_worker() is True
    v108._worker(object(), "coinbase", broker, (1, 2), "test")

    assert broker._startup_position_sync_adopted is True
    assert broker._startup_position_sync_fetch_ok is False
    assert any(item[0] == "publish" for item in calls)
