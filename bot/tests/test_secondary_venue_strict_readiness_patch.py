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


def test_strict_readiness_requires_both_connected_venues(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    _set_ready_env(monkeypatch, "coinbase")
    _set_ready_env(monkeypatch, "okx")
    monkeypatch.setattr(
        patch,
        "_runtime_brokers",
        lambda: {"coinbase": _Broker("coinbase", True), "okx": _Broker("okx", False)},
    )

    ready, missing, statuses = patch.refresh_readiness(force_log=True)

    assert ready is False
    assert missing == ["okx"]
    assert statuses["coinbase"]["ready"] is True
    assert statuses["okx"]["ready"] is False
    assert patch.os.environ["NIJA_REQUIRED_VENUES_READY"] == "0"


def test_strict_readiness_passes_only_when_both_are_ready(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    _set_ready_env(monkeypatch, "coinbase")
    _set_ready_env(monkeypatch, "okx")
    monkeypatch.setattr(
        patch,
        "_runtime_brokers",
        lambda: {"coinbase": _Broker("coinbase", True), "okx": _Broker("okx", True)},
    )

    ready, missing, _statuses = patch.refresh_readiness(force_log=True)

    assert ready is True
    assert missing == []
    assert patch.os.environ["NIJA_MULTI_BROKER_TRADING_READY"] == "1"


def test_pipeline_blocks_new_entry_but_allows_exit(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    monkeypatch.setattr(
        patch,
        "refresh_readiness",
        lambda **kwargs: (False, ["coinbase", "okx"], {}),
    )
    module = ModuleType("test_execution_pipeline")
    module.ExecutionPipeline = _ExecutionPipeline
    module.PipelineResult = _PipelineResult

    assert patch._patch_execution_pipeline(module) is True
    pipeline = module.ExecutionPipeline()

    entry = SimpleNamespace(
        symbol="BTC-USD",
        side="buy",
        size_usd=25.0,
        intent_type="entry",
        reduce_only=False,
        position_effect=None,
    )
    result = pipeline.execute(entry)
    assert result.success is False
    assert "required_secondary_venues_not_ready" in result.error

    exit_request = SimpleNamespace(
        symbol="BTC-USD",
        side="sell",
        size_usd=25.0,
        intent_type="exit",
        reduce_only=True,
        position_effect="close",
    )
    assert pipeline.execute(exit_request) == "executed"


def test_strategy_entry_eligibility_is_blocked_until_required_venues_ready(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "true")
    monkeypatch.setattr(
        patch,
        "refresh_readiness",
        lambda **kwargs: (False, ["okx"], {}),
    )
    module = ModuleType("test_trading_strategy")
    module.TradingStrategy = _TradingStrategy

    assert patch._patch_trading_strategy(module) is True
    allowed, reason = module.TradingStrategy()._is_broker_eligible_for_entry(_Broker("kraken"))

    assert allowed is False
    assert "okx" in reason


def test_strict_mode_disabled_preserves_upstream_execution(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setenv("NIJA_REQUIRE_SECONDARY_VENUES_READY", "false")
    module = ModuleType("test_execution_pipeline_disabled")
    module.ExecutionPipeline = _ExecutionPipeline
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
