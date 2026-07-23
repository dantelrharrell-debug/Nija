from __future__ import annotations

import importlib
from types import ModuleType, SimpleNamespace

import bot.downstream_risk_governor_equity_repair_patch as patch


class Result:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class RiskEngine:
    def __init__(self, headroom=100.0, error=None):
        self.headroom = headroom
        self.error = error

    def get_remaining_headroom_usd(self, account_id, available_balance):
        if self.error:
            raise self.error
        return self.headroom


def _request(**overrides):
    values = dict(
        symbol="BTC-USD",
        side="buy",
        size_usd=25.0,
        intent_type="entry",
        reduce_only=False,
        account_id="platform",
        preferred_broker="kraken",
        available_balance_usd=100.0,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _module(base_execute):
    module = ModuleType("bot.execution_pipeline")
    module.PipelineResult = Result
    module.normalize_pipeline_request = lambda request: request
    module.ExecutionPipeline = type("ExecutionPipeline", (), {"execute": base_execute})
    return module


def test_chain_marker_prevents_rewrapping_when_another_guard_is_outer(monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    def base(self, request):
        return "executed"

    module = _module(base)
    assert patch._install_on_execution_pipeline(module) is True
    risk_wrapper = module.ExecutionPipeline.execute

    def broker_local_outer(self, request):
        return risk_wrapper(self, request)

    broker_local_outer.__wrapped__ = risk_wrapper
    module.ExecutionPipeline.execute = broker_local_outer

    before = module.ExecutionPipeline.execute
    assert patch._install_on_execution_pipeline(module) is True
    assert module.ExecutionPipeline.execute is before
    found, cycle, depth = patch._chain_contains(before, patch._PIPELINE_ATTR)
    assert found is True
    assert cycle is False
    assert depth == 1


def test_same_thread_recursive_entry_is_denied_not_recurred(monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    def recursive_base(self, request):
        return self.execute(request)

    module = _module(recursive_base)
    patch._install_on_execution_pipeline(module)
    pipeline = module.ExecutionPipeline()
    pipeline._pre_trade_risk_engine = RiskEngine(headroom=100.0)

    result = pipeline.execute(_request())

    assert result.success is False
    assert result.error == "PRE_DISPATCH_RISK_REENTRANCY_BLOCKED"


def test_risk_sizing_exception_fails_closed_and_releases_token(monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    calls = []

    def base(self, request):
        calls.append(request.size_usd)
        return "executed"

    module = _module(base)
    patch._install_on_execution_pipeline(module)
    pipeline = module.ExecutionPipeline()
    pipeline._pre_trade_risk_engine = RiskEngine(error=RuntimeError("boom"))

    denied = pipeline.execute(_request())
    assert denied.success is False
    assert denied.error.startswith("PRE_DISPATCH_RISK_SIZING_ERROR:RuntimeError:boom")

    pipeline._pre_trade_risk_engine = RiskEngine(headroom=100.0)
    assert pipeline.execute(_request()) == "executed"
    assert calls == [25.0]


def test_live_entry_without_risk_engine_fails_closed(monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    def base(self, request):
        raise AssertionError("entry must not dispatch")

    module = _module(base)
    patch._install_on_execution_pipeline(module)
    result = module.ExecutionPipeline().execute(_request())

    assert result.success is False
    assert result.error == "PRE_DISPATCH_RISK_ENGINE_UNAVAILABLE"


def test_exit_bypasses_entry_sizing_and_reaches_original(monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    calls = []

    def base(self, request):
        calls.append((request.side, request.intent_type, request.reduce_only))
        return "exit-dispatched"

    module = _module(base)
    patch._install_on_execution_pipeline(module)
    pipeline = module.ExecutionPipeline()

    result = pipeline.execute(_request(side="sell", intent_type="exit", reduce_only=True))

    assert result == "exit-dispatched"
    assert calls == [("sell", "exit", True)]


def test_entry_is_clipped_to_verified_headroom(monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("KRAKEN_MIN_NOTIONAL_USD", "10")
    calls = []

    def base(self, request):
        calls.append(request.size_usd)
        return "executed"

    module = _module(base)
    patch._install_on_execution_pipeline(module)
    pipeline = module.ExecutionPipeline()
    pipeline._pre_trade_risk_engine = RiskEngine(headroom=20.0)

    assert pipeline.execute(_request(size_usd=25.0)) == "executed"
    assert len(calls) == 1
    assert 19.8 <= calls[0] < 20.0


def test_try_patch_loaded_imports_pretrade_module_when_not_loaded(monkeypatch):
    imported = []
    pretrade = ModuleType("bot.pre_trade_risk_engine")

    class Decision:
        def __init__(self, approved=True, reason="", details=None):
            self.approved = approved
            self.reason = reason
            self.details = details or {}

    class Engine:
        def assess(self, **kwargs):
            return Decision()

    pretrade.PreTradeRiskEngine = Engine
    pretrade.PreTradeRiskDecision = Decision

    monkeypatch.delitem(patch.sys.modules, "bot.pre_trade_risk_engine", raising=False)
    monkeypatch.delitem(patch.sys.modules, "pre_trade_risk_engine", raising=False)

    real_import = importlib.import_module

    def fake_import(name, package=None):
        imported.append(name)
        if name == "bot.pre_trade_risk_engine":
            patch.sys.modules[name] = pretrade
            return pretrade
        return real_import(name, package)

    monkeypatch.setattr(patch.importlib, "import_module", fake_import)
    monkeypatch.setitem(patch._STATE, "pretrade", False)

    assert patch._try_patch_loaded() is True
    assert imported[0] == "bot.pre_trade_risk_engine"
    assert patch._STATE["pretrade"] is True
    assert getattr(pretrade.PreTradeRiskEngine.assess, patch._PRETRADE_ATTR) is True
