from __future__ import annotations

import os
from types import ModuleType, SimpleNamespace

from bot import broker_context_locality_v422_patch as locality
from bot import core_loop_broker_argument_guard_patch as core_guard


class _BrokerType:
    def __init__(self, value: str):
        self.value = value


class _Broker:
    def __init__(self, name: str, account_id: str = "platform"):
        self.broker_type = _BrokerType(name)
        self.account_id = account_id

    def get_account_balance(self):
        return 100.0


def test_core_loop_ignores_conflicting_process_env(monkeypatch):
    kraken = _Broker("kraken")
    apex = SimpleNamespace(
        broker_client=kraken,
        broker=kraken,
        _nija_selected_execution_broker="kraken",
    )
    core = SimpleNamespace(apex=apex)

    monkeypatch.setenv("NIJA_SELECTED_EXECUTION_BROKER", "coinbase")
    monkeypatch.setenv("NIJA_PRIMARY_EXECUTION_BROKER", "coinbase")

    assert core_guard._resolve_broker(core, None) is kraken


def test_locality_patch_does_not_write_selected_broker_env(monkeypatch):
    monkeypatch.setenv("NIJA_SELECTED_EXECUTION_BROKER", "sentinel")
    monkeypatch.setenv("NIJA_PRIMARY_EXECUTION_BROKER", "sentinel-primary")

    module = ModuleType("fake_broker_independent")
    module._set_apex_broker_context = lambda *_args: {}
    module._restore_apex_broker_context = lambda *_args: None
    assert locality._patch_broker_independent(module) is True

    kraken = _Broker("kraken", "acct-a")
    apex = SimpleNamespace(broker_manager=SimpleNamespace(active_broker=None))
    old = module._set_apex_broker_context(apex, "kraken", kraken)
    try:
        assert apex.broker_client is kraken
        assert apex._nija_selected_execution_broker == "kraken"
        assert os.environ["NIJA_SELECTED_EXECUTION_BROKER"] == "sentinel"
        assert os.environ["NIJA_PRIMARY_EXECUTION_BROKER"] == "sentinel-primary"
    finally:
        module._restore_apex_broker_context(apex, old)


def test_route_resolver_prefers_request_or_context_not_environment(monkeypatch):
    monkeypatch.setenv("NIJA_SELECTED_EXECUTION_BROKER", "coinbase")
    monkeypatch.setenv("NIJA_PRIMARY_EXECUTION_BROKER", "coinbase")

    module = ModuleType("fake_execution_route_integrity")
    module._normalise_broker_name = lambda value: str(value or "").strip().lower()
    module._broker_key_from_obj = lambda obj: getattr(getattr(obj, "broker_type", None), "value", "unknown")
    module._allowed_brokers = lambda: ["kraken", "coinbase"]
    module._EQUITY_SURFACE_BY_CRYPTO_BROKER = {}
    module._set_strategy_broker = lambda *_args: None
    module._resolve_selected_broker = lambda *_args: "legacy"

    assert locality._patch_route_integrity(module) is True

    request = SimpleNamespace(
        preferred_broker="kraken",
        asset_class="crypto",
        metadata={},
    )
    assert module._resolve_selected_broker(request) == "kraken"
