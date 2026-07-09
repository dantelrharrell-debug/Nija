from __future__ import annotations

from types import SimpleNamespace

from bot import direct_broker_metadata_guard_patch as patch


class FakeRouter:
    def __init__(self):
        self.resolve_calls = 0
        self.dispatch_calls = 0

    def _resolve_live_broker(self, broker_name):
        self.resolve_calls += 1
        return None

    def _dispatch_via_inner_router(self, *args, **kwargs):
        self.dispatch_calls += 1
        return {"dispatched": True}


class FakeMultiBrokerExecutionRouter(FakeRouter):
    def _profile_for_direct_broker(self, asset_class, request):
        return {"profile": True}


def test_binance_is_unconfigured_without_explicit_env(monkeypatch):
    monkeypatch.delenv("NIJA_ENABLE_BINANCE", raising=False)
    monkeypatch.delenv("ENABLE_BINANCE", raising=False)
    monkeypatch.delenv("BINANCE_ENABLED", raising=False)
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)

    assert patch._is_configured_target("binance") is False
    assert patch._is_configured_target("kraken") is True


def test_resolve_live_client_does_not_scan_unconfigured_binance(monkeypatch):
    monkeypatch.delenv("NIJA_ENABLE_BINANCE", raising=False)
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    router = FakeRouter()

    client = patch._resolve_live_client(router, "binance", symbol="AI-USD")

    assert client is None
    assert router.resolve_calls == 0


def test_profile_returns_none_for_unconfigured_binance(monkeypatch):
    monkeypatch.delenv("NIJA_ENABLE_BINANCE", raising=False)
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    module = SimpleNamespace(MultiBrokerExecutionRouter=FakeMultiBrokerExecutionRouter, __name__="bot.multi_broker_execution_router")

    assert patch._patch_router(module) is True
    router = module.MultiBrokerExecutionRouter()
    request = SimpleNamespace(symbol="AI-USD", preferred_broker="binance", metadata={"preferred_broker": "binance"})

    assert router._profile_for_direct_broker("spot", request) is None


def test_dispatch_returns_none_for_unconfigured_binance(monkeypatch):
    monkeypatch.delenv("NIJA_ENABLE_BINANCE", raising=False)
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    module = SimpleNamespace(MultiBrokerExecutionRouter=FakeMultiBrokerExecutionRouter, __name__="bot.multi_broker_execution_router")

    assert patch._patch_router(module) is True
    router = module.MultiBrokerExecutionRouter()

    assert router._dispatch_via_inner_router(None, None, None, None, None, "binance", {}) is None
    assert router.dispatch_calls == 0
