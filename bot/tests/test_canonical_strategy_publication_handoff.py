from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _load(relative_path: str, module_name: str):
    root = Path(__file__).resolve().parents[2]
    path = root / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_synchronous_publication_builds_and_exports_strategy(monkeypatch) -> None:
    module = _load(
        "bot/strategy_publication_patch.py",
        "nija_test_strategy_publication_patch",
    )
    broker = SimpleNamespace(
        connected=True,
        exit_only_mode=False,
        broker_type=SimpleNamespace(value="kraken"),
    )
    published_to = ModuleType("published_target")

    class FakeStrategy:
        def __init__(self, broker_results=None):
            self.broker = next(iter(broker_results.values()))["broker"]
            self.symbols = ["BTC-USD"]
            self.nija_core_loop = object()

        def run_cycle(self):
            return None

    monkeypatch.setattr(module, "_strategy_class", lambda: FakeStrategy)
    monkeypatch.setattr(module, "_broker_results", lambda: ({}, 0))
    monkeypatch.setattr(module, "_modules", lambda: [published_to])
    module._PUBLISHED = None

    strategy, detail = module.publish_canonical_strategy(
        explicit_broker=broker,
    )

    assert isinstance(strategy, FakeStrategy)
    assert strategy.broker is broker
    assert detail == "built_published"
    assert published_to.nija_live_strategy is strategy
    assert published_to._initialized_state["strategy"] is strategy


def test_synchronous_publication_rejects_missing_entry_broker(monkeypatch) -> None:
    module = _load(
        "bot/strategy_publication_patch.py",
        "nija_test_strategy_publication_patch_no_broker",
    )

    class FakeStrategy:
        def run_cycle(self):
            return None

    monkeypatch.setattr(module, "_strategy_class", lambda: FakeStrategy)
    monkeypatch.setattr(module, "_broker_results", lambda: ({}, 0))
    module._PUBLISHED = None

    strategy, detail = module.publish_canonical_strategy()

    assert strategy is None
    assert detail == "no_entry_ready_brokers"


def test_bot_main_hands_off_published_strategy(monkeypatch) -> None:
    module = _load("bot/bot_main.py", "nija_test_bot_main_handoff")
    broker = SimpleNamespace(connected=True)
    strategy = SimpleNamespace(broker=broker, run_cycle=lambda: None)
    publication = ModuleType("bot.strategy_publication_patch")
    calls: list[object] = []

    def publish_canonical_strategy(explicit_broker=None):
        calls.append(explicit_broker)
        return strategy, "built_published"

    publication.publish_canonical_strategy = publish_canonical_strategy
    monkeypatch.setitem(
        sys.modules,
        "bot.strategy_publication_patch",
        publication,
    )

    result = module._publish_canonical_strategy_for_runtime(broker)

    assert result is strategy
    assert calls == [broker]


def test_bot_main_revokes_runtime_claims_when_publication_fails(
    monkeypatch,
) -> None:
    module = _load("bot/bot_main.py", "nija_test_bot_main_fail_closed")
    publication = ModuleType("bot.strategy_publication_patch")
    publication.publish_canonical_strategy = (
        lambda explicit_broker=None: (None, "no_entry_ready_brokers")
    )
    monkeypatch.setitem(
        sys.modules,
        "bot.strategy_publication_patch",
        publication,
    )
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_ACTIVE")

    result = module._publish_canonical_strategy_for_runtime(
        SimpleNamespace(connected=True)
    )

    assert result is None
    assert module.os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert module.os.environ["NIJA_RUNTIME_TRADING_STATE"] == "OFF"


def test_strategy_monitor_install_is_deferred_until_explicit_start(monkeypatch) -> None:
    module = _load(
        "bot/strategy_publication_patch.py",
        "nija_test_strategy_publication_patch_monitor",
    )
    started: list[str] = []

    class FakeThread:
        def __init__(self, target=None, name=None, daemon=None):
            self.target = target
            self.name = name
            self.daemon = daemon

        def start(self):
            started.append("started")

        def is_alive(self):
            return True

    monkeypatch.setattr(module.threading, "Thread", FakeThread)

    module.install_import_hook()
    assert started == []

    assert module.start_monitor() is True
    assert started == ["started"]


def test_bot_main_treats_lock_contention_as_safe_standby(monkeypatch) -> None:
    module = _load("bot/bot_main.py", "nija_test_bot_main_lock_contention")
    monkeypatch.setattr(module.signal, "signal", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_acquire_writer_authority_before_nonce", lambda: False)
    monkeypatch.setattr(module, "_release_writer_authority", lambda: None)
    module._shutdown_event.clear()
    module._writer_authority_last_error = "active_writer_lock_held"

    assert module.main() == 0
