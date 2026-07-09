from __future__ import annotations

from types import SimpleNamespace

from bot import final_stage_venue_resolution_cache_patch as patch


class KrakenBroker:
    connected = True

    def get_account_balance(self):
        return 332.54

    def place_market_order(self, *args, **kwargs):
        return {"ok": True}


class MultiBrokerExecutionRouter:
    calls = 0

    def _resolve_live_broker(self, broker_name):
        self.calls += 1
        return KrakenBroker()


def test_resolution_cache_returns_cached_client(monkeypatch):
    monkeypatch.setenv("NIJA_FINAL_STAGE_BROKER_RESOLUTION_CACHE_TTL_S", "20")
    module = SimpleNamespace(MultiBrokerExecutionRouter=MultiBrokerExecutionRouter, __name__="bot.multi_broker_execution_router")

    assert patch._patch_router_module(module) is True
    router = module.MultiBrokerExecutionRouter()
    first = router._resolve_live_broker("kraken")
    second = router._resolve_live_broker("kraken")

    assert first is second
    assert router.calls == 1
