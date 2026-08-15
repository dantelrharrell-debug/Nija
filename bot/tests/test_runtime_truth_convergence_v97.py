from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from bot import empty_position_sync_success_patch as empty_sync_patch
from bot import runtime_truth_convergence_v97_patch as patch


def test_canonical_fast_path_installs_v97_before_strategy_integrity() -> None:
    source = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    installers = None
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "_FAST_PATH_INSTALLERS":
                    installers = list(ast.literal_eval(node.value))
    assert installers is not None
    modules = [name for name, _label in installers]
    assert modules.index("bot.trading_strategy_apex_wiring_patch") < modules.index(
        "bot.runtime_truth_convergence_v97_patch"
    ) < modules.index("bot.strategy_runtime_integrity_patch")


def test_apex_recovery_loads_class_from_source_when_partial_module_has_no_class(tmp_path, monkeypatch) -> None:
    source = tmp_path / "nija_apex_strategy_v71.py"
    source.write_text("class NIJAApexStrategyV71:\n    pass\n", encoding="utf-8")
    wiring = ModuleType("test_wiring")
    wiring.__file__ = str(tmp_path / "trading_strategy_apex_wiring_patch.py")

    partial = ModuleType("bot.nija_apex_strategy_v71")
    partial.__file__ = str(source)
    monkeypatch.setitem(sys.modules, "bot.nija_apex_strategy_v71", partial)
    monkeypatch.delitem(sys.modules, "nija_apex_strategy_v71", raising=False)
    monkeypatch.delitem(sys.modules, patch._RECOVERY_MODULE, raising=False)
    monkeypatch.setattr(patch, "_RECOVERED_APEX_CLASS", None)

    cls, recovered_from = patch._recover_apex_class_from_source(wiring)

    assert cls is not None
    assert cls.__name__ == "NIJAApexStrategyV71"
    assert recovered_from == patch._RECOVERY_MODULE
    assert getattr(partial, "NIJAApexStrategyV71") is cls


def test_partial_apex_preempts_recursive_legacy_resolver_on_source_loaded_alias(tmp_path, monkeypatch) -> None:
    source = tmp_path / "nija_apex_strategy_v71.py"
    source.write_text("class NIJAApexStrategyV71:\n    pass\n", encoding="utf-8")

    calls: list[str] = []
    wiring = ModuleType("nija_trading_strategy_apex_wiring_patch")
    wiring.__file__ = str(tmp_path / "trading_strategy_apex_wiring_patch.py")

    def recursive_legacy_resolver():
        calls.append("legacy")
        raise RecursionError("flat alias loop")

    wiring._resolve_apex_class = recursive_legacy_resolver
    partial = ModuleType("bot.nija_apex_strategy_v71")
    partial.__file__ = str(source)

    monkeypatch.setitem(sys.modules, "nija_trading_strategy_apex_wiring_patch", wiring)
    monkeypatch.setitem(sys.modules, "bot.nija_apex_strategy_v71", partial)
    monkeypatch.delitem(sys.modules, "nija_apex_strategy_v71", raising=False)
    monkeypatch.delitem(sys.modules, patch._RECOVERY_MODULE, raising=False)
    monkeypatch.setattr(patch, "_RECOVERED_APEX_CLASS", None)

    assert patch._patch_apex_wiring(wiring)
    cls, recovered_from = wiring._resolve_apex_class()

    assert cls is not None
    assert cls.__name__ == "NIJAApexStrategyV71"
    assert recovered_from == patch._RECOVERY_MODULE
    assert calls == []
    assert getattr(partial, "NIJAApexStrategyV71") is cls


def test_patch_loaded_discovers_source_loaded_wiring_alias_by_file(tmp_path, monkeypatch) -> None:
    source = tmp_path / "nija_apex_strategy_v71.py"
    source.write_text("class NIJAApexStrategyV71:\n    pass\n", encoding="utf-8")

    wiring = ModuleType("runtime_alias_which_does_not_match_canonical_name")
    wiring.__file__ = str(tmp_path / "trading_strategy_apex_wiring_patch.py")
    wiring._resolve_apex_class = lambda: (None, "legacy_missing")
    partial = ModuleType("bot.nija_apex_strategy_v71")
    partial.__file__ = str(source)

    monkeypatch.setitem(sys.modules, wiring.__name__, wiring)
    monkeypatch.setitem(sys.modules, "bot.nija_apex_strategy_v71", partial)
    monkeypatch.delitem(sys.modules, patch._RECOVERY_MODULE, raising=False)
    monkeypatch.setattr(patch, "_RECOVERED_APEX_CLASS", None)

    patch._patch_loaded()

    assert getattr(wiring._resolve_apex_class, patch._APEX_ATTR, False) is True
    cls, _source = wiring._resolve_apex_class()
    assert cls is not None
    assert cls.__name__ == "NIJAApexStrategyV71"


def test_position_fetch_failure_revokes_previous_sync_success(monkeypatch) -> None:
    class KrakenBroker:
        def __init__(self) -> None:
            self._startup_position_sync_adopted = True

        def get_positions(self):
            raise TimeoutError("slow exchange")

    module = ModuleType("test_broker_manager")
    module.KrakenBroker = KrakenBroker
    assert patch._patch_position_broker_module(module)

    broker = KrakenBroker()
    monkeypatch.setenv("NIJA_POSITION_SYNC_ACTIVATION_READY", "1")
    monkeypatch.setenv("NIJA_POSITION_SYNC_DISPATCH_READY", "1")

    with pytest.raises(TimeoutError):
        broker.get_positions()

    assert broker._startup_position_sync_adopted is False
    assert broker._startup_position_sync_fetch_ok is False
    assert "TimeoutError" in broker._startup_position_sync_error
    assert patch.os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] == "0"
    assert patch.os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] == "0"


def test_nested_position_wrapper_preserves_failure_masked_as_empty(monkeypatch) -> None:
    class KrakenBroker:
        def __init__(self) -> None:
            self._startup_position_sync_adopted = True

    def raw_get_positions(self):
        raise TimeoutError("slow exchange")

    inner = patch._wrap_position_fetch(raw_get_positions, "kraken")

    def compatibility_equity_wrapper(self):
        try:
            return inner(self)
        except TimeoutError:
            return []

    outer = patch._wrap_position_fetch(compatibility_equity_wrapper, "kraken")
    broker = KrakenBroker()
    monkeypatch.setenv("NIJA_POSITION_SYNC_ACTIVATION_READY", "1")
    monkeypatch.setenv("NIJA_POSITION_SYNC_DISPATCH_READY", "1")

    assert outer(broker) == []
    assert broker._startup_position_sync_fetch_ok is False
    assert broker._startup_position_sync_adopted is False
    assert "TimeoutError" in broker._startup_position_sync_error
    assert patch.os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] == "0"
    assert patch.os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] == "0"


def test_startup_sync_guard_rejects_masked_empty_success(monkeypatch) -> None:
    class Broker:
        _startup_position_sync_adopted = False
        _startup_position_sync_fetch_ok = None
        _startup_position_sync_error = None

    def canonical_adopt(broker, broker_name, eps):
        broker._startup_position_sync_fetch_ok = False
        broker._startup_position_sync_error = "TimeoutError:slow exchange"
        broker._startup_position_sync_adopted = True
        return 0

    module = ModuleType("bot.startup_position_sync")
    module._adopt_broker_positions = canonical_adopt
    assert patch._patch_startup_sync_module(module)

    broker = Broker()
    monkeypatch.setenv("NIJA_POSITION_SYNC_ACTIVATION_READY", "1")
    monkeypatch.setenv("NIJA_POSITION_SYNC_DISPATCH_READY", "1")
    assert module._adopt_broker_positions(broker, "platform:kraken", None) == 0

    assert broker._startup_position_sync_adopted is False
    assert broker._startup_position_sync_fetch_ok is False
    assert patch.os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] == "0"
    assert patch.os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] == "0"


def test_empty_sync_compatibility_wrapper_never_refetches_broker() -> None:
    calls: list[str] = []

    class Broker:
        connected = True
        _startup_position_sync_adopted = False
        _startup_position_sync_fetch_ok = True

        def get_positions(self):
            raise AssertionError("compatibility wrapper must not refetch")

    def canonical_adopt(broker, broker_name, eps):
        calls.append(broker_name)
        broker._startup_position_sync_adopted = True
        return 0

    module = ModuleType("bot.startup_position_sync")
    module._adopt_broker_positions = canonical_adopt
    assert empty_sync_patch._patch(module)

    broker = Broker()
    assert module._adopt_broker_positions(broker, "platform:kraken", None) == 0
    assert calls == ["platform:kraken"]
    assert broker._startup_position_sync_adopted is True


def test_empty_sync_compatibility_wrapper_preserves_failure_proof() -> None:
    class Broker:
        connected = True
        _startup_position_sync_adopted = False
        _startup_position_sync_fetch_ok = False
        _startup_position_sync_error = "TimeoutError:slow exchange"

    def canonical_adopt(broker, broker_name, eps):
        broker._startup_position_sync_adopted = True
        return 0

    module = ModuleType("bot.startup_position_sync")
    module._adopt_broker_positions = canonical_adopt
    assert empty_sync_patch._patch(module)

    broker = Broker()
    assert module._adopt_broker_positions(broker, "platform:kraken", None) == 0
    assert broker._startup_position_sync_adopted is False


def test_scan_phase_records_writer_lifecycle(monkeypatch) -> None:
    events: list[str] = []
    runtime = SimpleNamespace(
        record_scan_started=lambda: events.append("started"),
        record_scan_complete=lambda: events.append("complete"),
    )
    writer = ModuleType("bot.entrypoint_writer_authority")
    writer.get_entrypoint_writer_authority = lambda: runtime
    monkeypatch.setitem(sys.modules, "bot.entrypoint_writer_authority", writer)

    class NijaCoreLoop:
        def run_scan_phase(self):
            events.append("scan")
            return "ok"

    core = ModuleType("bot.nija_core_loop")
    core.NijaCoreLoop = NijaCoreLoop
    assert patch._patch_core_loop(core)

    assert NijaCoreLoop().run_scan_phase() == "ok"
    assert events == ["started", "scan", "complete"]
