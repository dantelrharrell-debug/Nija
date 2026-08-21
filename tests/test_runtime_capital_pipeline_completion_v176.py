from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import bot.runtime_capital_pipeline_completion_v176_patch as v176


def test_proactive_deadline_uses_existing_v166_bound(monkeypatch):
    fake_v142 = SimpleNamespace(_runtime_pipeline_deadline_seconds=lambda: 80.0)
    fake_v166 = SimpleNamespace(
        _is_proactive_trigger=lambda value=None: True,
        _proactive_pipeline_deadline_seconds=lambda: 50.0,
    )
    monkeypatch.setattr(v176, "_v142", lambda: fake_v142)
    monkeypatch.setattr(v176, "_v166", lambda: fake_v166)

    assert v176._patch_proactive_deadline_context() is True
    assert fake_v142._runtime_pipeline_deadline_seconds() == 50.0


def test_non_proactive_deadline_preserves_existing_bound(monkeypatch):
    fake_v142 = SimpleNamespace(_runtime_pipeline_deadline_seconds=lambda: 80.0)
    fake_v166 = SimpleNamespace(
        _is_proactive_trigger=lambda value=None: False,
        _proactive_pipeline_deadline_seconds=lambda: 50.0,
    )
    monkeypatch.setattr(v176, "_v142", lambda: fake_v142)
    monkeypatch.setattr(v176, "_v166", lambda: fake_v166)

    assert v176._patch_proactive_deadline_context() is True
    assert fake_v142._runtime_pipeline_deadline_seconds() == 80.0


def test_execute_wrapper_sets_and_restores_caller_context(monkeypatch):
    context = {"trigger": "before"}
    observed: list[str] = []

    def set_trigger(value):
        previous = context["trigger"]
        context["trigger"] = str(value)
        return previous

    def restore_trigger(previous):
        context["trigger"] = previous

    class Coordinator:
        def execute_refresh(self, broker_map, trigger="coordinator", open_exposure_usd=0.0):
            observed.append(context["trigger"])
            return "ok"

    fake_v166 = SimpleNamespace(
        _set_trigger=set_trigger,
        _restore_trigger=restore_trigger,
        _is_proactive_trigger=lambda value=None: str(value or context["trigger"]).startswith(
            "publication_deadline_v137"
        ),
    )
    fake_v142 = SimpleNamespace(_runtime_pipeline_deadline_seconds=lambda: 50.0)
    monkeypatch.setattr(v176, "_flow", lambda: SimpleNamespace(CapitalRefreshCoordinator=Coordinator))
    monkeypatch.setattr(v176, "_v166", lambda: fake_v166)
    monkeypatch.setattr(v176, "_v142", lambda: fake_v142)

    assert v176._patch_execute_trigger_context() is True
    coordinator = Coordinator()
    result = coordinator.execute_refresh({}, trigger="publication_deadline_v137")

    assert result == "ok"
    assert observed == ["publication_deadline_v137"]
    assert context["trigger"] == "before"


def test_persistence_remains_synchronous_outside_live_runtime(monkeypatch):
    calls: list[str] = []

    class CapitalAuthority:
        def _save_cached_state(self):
            calls.append("saved")

    real_import = v176.importlib.import_module

    def fake_import(name: str):
        if name == "bot.capital_authority":
            return SimpleNamespace(CapitalAuthority=CapitalAuthority)
        return real_import(name)

    monkeypatch.setattr(v176.importlib, "import_module", fake_import)
    monkeypatch.delenv("LIVE_CAPITAL_VERIFIED", raising=False)
    monkeypatch.delenv("DRY_RUN_MODE", raising=False)
    monkeypatch.delenv("PAPER_MODE", raising=False)

    assert v176._patch_async_best_effort_persistence() is True
    CapitalAuthority()._save_cached_state()
    assert calls == ["saved"]


def test_v176_source_preserves_fail_closed_contract():
    source = Path(v176.__file__).read_text(encoding="utf-8")
    forbidden = (
        "accept_partial_snapshot(",
        "extend_freshness(",
        "force_activation(",
        "grant_execution_authority(",
        "force_trade(",
    )
    for token in forbidden:
        assert token not in source

    assert "partial_aggregation_gate_unchanged=true" in source
    assert "freshness_extended=false" in source
    assert "publication_expiry_extended=false" in source
    assert "safety_gates_bypassed=false" in source
