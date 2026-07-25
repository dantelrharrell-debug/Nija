from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


MODULE_PATH = Path(__file__).resolve().parents[1] / "startup_position_sync.py"


def _load_module():
    name = f"startup_position_sync_dispatch_{uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_strategy_is_published_only_after_position_sync_completes(monkeypatch) -> None:
    module = _load_module()
    strategy = object()
    broker = SimpleNamespace(position_tracker=None, _startup_position_sync_adopted=True)

    monkeypatch.setattr(
        module,
        "_collect_connected_brokers",
        lambda candidate: {"platform:kraken": broker},
    )
    monkeypatch.setattr(module, "_get_entry_price_store", lambda: None)
    monkeypatch.setattr(module, "_adopt_broker_positions", lambda *args: 0)
    monkeypatch.setattr(module, "_tracker_count", lambda tracker: 0)

    assert module._LAST_COMPLETED_STRATEGY is None

    module.sync_exchange_positions_on_startup(strategy)

    assert module._LAST_COMPLETED_STRATEGY is strategy


def test_strategy_is_not_published_when_no_broker_is_connected(monkeypatch) -> None:
    module = _load_module()
    strategy = object()
    monkeypatch.setattr(module, "_collect_connected_brokers", lambda candidate: {})
    monkeypatch.setattr(module, "_get_entry_price_store", lambda: None)

    module.sync_exchange_positions_on_startup(strategy)

    assert module._LAST_COMPLETED_STRATEGY is None
