from __future__ import annotations

from types import SimpleNamespace

from bot import operator_emergency_stop_preexec_clear_patch as patch


class FakeExecutionEngine:
    def __init__(self):
        self.called = False

    def execute_entry(self, *args, **kwargs):
        self.called = True
        return "executed"


class FakeKillSwitch:
    def __init__(self):
        self.checked = False

    def is_active(self):
        self.checked = True
        return False


def test_preexec_bridge_runs_operator_clear_before_execute_entry(monkeypatch):
    calls: list[str] = []

    def fake_clear(source: str):
        calls.append(source)
        return 1

    monkeypatch.setattr(patch, "_run_operator_clear", fake_clear)
    module = SimpleNamespace(ExecutionEngine=FakeExecutionEngine, __name__="bot.execution_engine")

    assert patch._patch_execution_module(module) is True
    engine = module.ExecutionEngine()

    assert engine.execute_entry("ATOM-USDT") == "executed"
    assert calls == ["pre_execute_entry"]
    assert engine.called is True


def test_preexec_bridge_runs_operator_clear_before_kill_switch_check(monkeypatch):
    calls: list[str] = []

    def fake_clear(source: str):
        calls.append(source)
        return 0

    monkeypatch.setattr(patch, "_run_operator_clear", fake_clear)
    module = SimpleNamespace(KillSwitch=FakeKillSwitch, __name__="bot.kill_switch")

    assert patch._patch_kill_switch_module(module) is True
    kill_switch = module.KillSwitch()

    assert kill_switch.is_active() is False
    assert calls == ["kill_switch.is_active"]
    assert kill_switch.checked is True


def test_operator_clear_hot_path_skips_without_real_candidate(monkeypatch):
    clear_module_calls: list[str] = []

    monkeypatch.setattr(
        patch,
        "_operator_clear_candidate_present",
        lambda: (False, "no_emergency_latch:runtime_state=OFF exec_auth=0"),
    )
    monkeypatch.setattr(
        patch,
        "_clear_patch_module",
        lambda: clear_module_calls.append("loaded") or SimpleNamespace(run_once=lambda: 1),
    )

    assert patch._run_operator_clear("kill_switch.is_active") == 0
    assert clear_module_calls == []


def test_operator_clear_candidate_runs_canonical_clear_once(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(
        patch,
        "_operator_clear_candidate_present",
        lambda: (True, "kill_file_present"),
    )
    monkeypatch.setattr(
        patch,
        "_clear_patch_module",
        lambda: SimpleNamespace(run_once=lambda: calls.append("run_once") or 0),
    )

    assert patch._run_operator_clear("kill_switch.is_active") == 0
    assert calls == ["run_once"]
