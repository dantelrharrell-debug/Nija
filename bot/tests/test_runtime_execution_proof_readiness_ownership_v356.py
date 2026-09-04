from types import SimpleNamespace

import bot.runtime_execution_proof_readiness_ownership_v356_patch as v356


def _fake_strategy_module(monkeypatch, calls):
    strategy_target = SimpleNamespace(_initialized_state={})

    class FakeBroker:
        connected = True

    strategy = SimpleNamespace(
        broker=FakeBroker(),
        nija_core_loop=object(),
        symbols=["BTC-USD"],
    )
    fake_logger = SimpleNamespace(
        critical=lambda *a, **k: None,
        info=lambda *a, **k: None,
        debug=lambda *a, **k: None,
    )
    fake_module = SimpleNamespace(
        _PUBLISHED=None,
        _modules=lambda: [strategy_target],
        _publish=lambda _strategy: None,
        logger=fake_logger,
    )
    fake_readiness = SimpleNamespace(mark_ready=lambda key: calls.append(key))
    fake_bootstrap = SimpleNamespace(_maybe_mark_bootstrap=lambda source: calls.append(f"bootstrap:{source}"))

    def fake_import(name):
        if name == "bot.strategy_publication_patch":
            return fake_module
        if name == "bot.readiness_table":
            return fake_readiness
        if name == "bot.post_lock_capital_refresh_patch":
            return fake_bootstrap
        raise ImportError(name)

    monkeypatch.setattr(v356.importlib, "import_module", fake_import)
    return fake_module, strategy_target, strategy


def test_strategy_publication_does_not_grant_execution_ready(monkeypatch):
    calls = []
    module, target, strategy = _fake_strategy_module(monkeypatch, calls)
    assert v356._patch_strategy_publish() is True

    module._publish(strategy)

    assert "strategy_ready" in calls
    assert "execution_ready" not in calls
    assert target._initialized_state["strategy"] is strategy
    assert module._PUBLISHED is strategy


def test_strategy_publication_preserves_bootstrap_recheck(monkeypatch):
    calls = []
    module, _target, strategy = _fake_strategy_module(monkeypatch, calls)
    assert v356._patch_strategy_publish() is True

    module._publish(strategy)

    assert "bootstrap:strategy_publication" in calls


def test_patch_is_idempotent(monkeypatch):
    calls = []
    module, _target, _strategy = _fake_strategy_module(monkeypatch, calls)
    assert v356._patch_strategy_publish() is True
    first = module._publish
    assert v356._patch_strategy_publish() is True
    assert module._publish is first
