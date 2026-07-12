from __future__ import annotations

from types import ModuleType, SimpleNamespace

import secondary_venue_strict_readiness_patch as patch


class _Broker:
    def __init__(self, name: str, connected: bool = True):
        self.broker_type = name
        self.connected = connected


class _PipelineResult:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _ExecutionPipeline:
    def execute(self, request):
        return "executed"


class _TradingStrategy:
    def _is_broker_eligible_for_entry(self, broker):
        return True, "upstream-ready"


def _reset(monkeypatch):
    patch._LAST_SIGNATURE = ""
    patch._PATCHED_PIPELINE.clear()
    patch._PATCHED_STRATEGY.clear()
    for name in (
        "NIJA_REQUIRE_SECONDARY_VENUES_READY",
        "NIJA_REQUIRED_LIVE_VENUES",
        "NIJA_COINBASE_ACTIVATION_STATE",
        "NIJA_COINBASE_CONNECTED",
        "NIJA_COINBASE_TRADING_READY",
        "NIJA_COINBASE_ACTIVATED",
        "NIJA_COINBASE_SPENDABLE_QUOTE",
        "NIJA_OKX_ACTIVATION_STATE",
        "NIJA_OKX_CONNECTED",
        "NIJA_OKX_TRADING_READY",
        "NIJA_OKX_ACTIVATED",
        "NIJA_OKX_SPENDABLE_QUOTE",
        "NIJA_REQUIRED_VENUES_READY",
        "NIJA_MULTI_BROKER_TRADING_READY",
        "NIJA_REQUIRED_VENUES_MISSING",
        "NIJA_ACTIVE_LIVE_VENUES",
        "NIJA_DEGRADED_LIVE_VENUES",
        "NIJA_REQUIRED_VENUES_STATUS_JSON",
        "NIJA_NEW_ENTRY_BLOCK_REASON",
    ):
        monkeypatch.delenv(name, raising=False)


def _set_ready_env(monkeypatch, venue: str):
    key = venue.upper()
    monkeypatch.setenv(f"NIJA_{key}_ACTIVATION_STATE", "ready")
    monkeypatch.setenv(f"NIJA_{key}_CONNECTED", "1")
    monkeypatch.setenv(f"NIJA_{key}_TRADING_READY", "1")
    monkeypatch.setenv(f"NIJA_{key}_ACTIVATED", "1")
    monkeypatch.setenv(f"NIJA_{key}_SPENDABLE_QUOTE", "25")


def test_refresh_reports_degraded_secondary_without_global_block(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    _set_ready_env(monkeypatch, "coinbase")
    _set_ready_env(monkeypatch, "okx")
    monkeypatch.setattr(
        patch,
        "_runtime_brokers",
        lambda: {
            "kraken": _Broker("kraken", True),
            "coinbase": _Broker("coinbase", True),
            "okx": _Broker("okx", False),
        },
    )

    ready, missing, statuses = patch.refresh_readiness(force_log=True)

    assert ready is True
    assert missing == ["okx"]
    assert statuses["kraken"]["ready"] is True
    assert statuses["coinbase"]["ready"] is True
    assert statuses["okx"]["ready"] is False
    assert patch.os.environ["NIJA_REQUIRED_VENUES_READY"] == "1"
    assert patch.os.environ["NIJA_MULTI_BROKER_TRADING_READY"] == "1"
    assert "NIJA_NEW_ENTRY_BLOCK_REASON" not in patch.os.environ


def test_pipeline_allows_kraken_when_secondary_venues_are_down(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    monkeypatch.setattr(
        patch,
        "_runtime_brokers",
        lambda: {
            "kraken": _Broker("kraken", True),
            "coinbase": _Broker("coinbase", False),
            "okx": _Broker("okx", False),
        },
    )
    module = ModuleType("test_execution_pipeline_kraken")
    module.ExecutionPipeline = type("ExecutionPipelineKraken", (_ExecutionPipeline,), {})
    module.PipelineResult = _PipelineResult

    assert patch._patch_execution_pipeline(module) is True
    request = SimpleNamespace(
        symbol="BTC-USD",
        side="buy",
        size_usd=25.0,
        preferred_broker="kraken",
        intent_type="entry",
        reduce_only=False,
        position_effect=None,
    )

    assert module.ExecutionPipeline().execute(request) == "executed"


def test_pipeline_blocks_only_the_unready_target_broker(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    monkeypatch.setenv("NIJA_OKX_ACTIVATION_STATE", "connect_failed")
    monkeypatch.setenv("NIJA_OKX_CONNECTED", "0")
    monkeypatch.setenv("NIJA_OKX_TRADING_READY", "0")
    monkeypatch.setenv("NIJA_OKX_ACTIVATED", "0")
    monkeypatch.setattr(patch, "_runtime_brokers", lambda: {"okx": _Broker("okx", False)})
    module = ModuleType("test_execution_pipeline_okx")
    module.ExecutionPipeline = type("ExecutionPipelineOkx", (_ExecutionPipeline,), {})
    module.PipelineResult = _PipelineResult

    assert patch._patch_execution_pipeline(module) is True
    request = SimpleNamespace(
        symbol="BTC-USDT",
        side="buy",
        size_usd=25.0,
        preferred_broker="okx",
        intent_type="entry",
        reduce_only=False,
        position_effect=None,
    )
    result = module.ExecutionPipeline().execute(request)

    assert result.success is False
    assert result.error.startswith("target_broker_not_ready:okx:")


def test_pipeline_without_target_leaves_routing_to_router(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    monkeypatch.setattr(
        patch,
        "_runtime_brokers",
        lambda: {"coinbase": _Broker("coinbase", False), "okx": _Broker("okx", False)},
    )
    module = ModuleType("test_execution_pipeline_auto")
    module.ExecutionPipeline = type("ExecutionPipelineAuto", (_ExecutionPipeline,), {})
    module.PipelineResult = _PipelineResult
    assert patch._patch_execution_pipeline(module) is True

    request = SimpleNamespace(
        symbol="ETH-USD",
        side="buy",
        size_usd=20.0,
        intent_type="entry",
        reduce_only=False,
        position_effect=None,
    )
    assert module.ExecutionPipeline().execute(request) == "executed"


def test_strategy_unready_okx_does_not_block_kraken(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    monkeypatch.setenv("NIJA_OKX_ACTIVATION_STATE", "connect_failed")
    module = ModuleType("test_trading_strategy_independent")
    module.TradingStrategy = type("TradingStrategyIndependent", (_TradingStrategy,), {})

    assert patch._patch_trading_strategy(module) is True
    strategy = module.TradingStrategy()
    kraken_allowed, kraken_reason = strategy._is_broker_eligible_for_entry(_Broker("kraken", True))
    okx_allowed, okx_reason = strategy._is_broker_eligible_for_entry(_Broker("okx", False))

    assert kraken_allowed is True
    assert kraken_reason == "upstream-ready"
    assert okx_allowed is False
    assert "okx" in okx_reason


def test_exits_always_bypass_broker_local_entry_guard(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    monkeypatch.setenv("NIJA_OKX_ACTIVATION_STATE", "connect_failed")
    monkeypatch.setattr(patch, "_runtime_brokers", lambda: {"okx": _Broker("okx", False)})
    module = ModuleType("test_execution_pipeline_exit")
    module.ExecutionPipeline = type("ExecutionPipelineExit", (_ExecutionPipeline,), {})
    module.PipelineResult = _PipelineResult
    assert patch._patch_execution_pipeline(module) is True

    request = SimpleNamespace(
        symbol="BTC-USDT",
        side="sell",
        size_usd=25.0,
        preferred_broker="okx",
        intent_type="exit",
        reduce_only=True,
        position_effect="close",
    )
    assert module.ExecutionPipeline().execute(request) == "executed"
