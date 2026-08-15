from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

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
    monkeypatch.setitem(sys.modules, "bot.nija_apex_strategy_v71", partial)
    monkeypatch.delitem(sys.modules, "nija_apex_strategy_v71", raising=False)
    monkeypatch.delitem(sys.modules, patch._RECOVERY_MODULE, raising=False)
    monkeypatch.setattr(patch, "_RECOVERED_APEX_CLASS", None)

    cls, recovered_from = patch._recover_apex_class_from_source(wiring)

    assert cls is not None
    assert cls.__name__ == "NIJAApexStrategyV71"
    assert recovered_from == patch._RECOVERY_MODULE
    assert getattr(partial, "NIJAApexStrategyV71") is cls


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
    assert "TimeoutError" in broker._startup_position_sync_error
    assert patch.os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] == "0"
    assert patch.os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] == "0"


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
